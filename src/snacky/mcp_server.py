"""The MCP tools the chat assistant logs food through.

The assistant names foods and amounts. Nutrient numbers come from a database
(stored foods, BLS, Open Food Facts, Tandoor). The assistant supplies numbers
in two cases only: values read off a nutrition label (`log_label`) and a plate
item nothing knows (`log_estimate`). Every result names the source.
"""

import functools
import inspect
import os
import re
import statistics
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from snacky import config
from snacky.lookup import Lookup, LookupFailed, is_good_match
from snacky.model import (
    Confidence,
    Entry,
    Food,
    FoodCandidate,
    Goal,
    GoalKind,
    GoalStatus,
    Nutrients,
    Origin,
    Serving,
    Source,
)
from snacky.sources.off import OffUnavailable
from snacky.sources.opengym import OpenGymClient, OpenGymError
from snacky.sources.tandoor import TandoorClient, TandoorError
from snacky.store import DuplicateEntry, NotFound, Store

# An eaten_at this far ahead of the clock is a wrong date, not a future meal.
_FUTURE_SLACK = timedelta(minutes=15)
_HHMM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

# How far back "recently eaten" reaches when suggesting foods.
_SUGGEST_DAYS = 30

NutrientName = Literal["kcal", "protein_g", "fat_g", "carbs_g", "fibre_g"]


def guarded(*errors: type[BaseException]) -> Callable:
    """Turn an expected failure into a ToolError, so the model reads the
    message and can correct its call. Anything else stays a crash."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                return await result if inspect.isawaitable(result) else result
            except ToolError:
                raise
            except errors as exc:
                raise ToolError(_describe(exc)) from exc

        return wrapper

    return deco


def _describe(exc: BaseException) -> str:
    if isinstance(exc, NotFound):
        return f"Nothing stored under {exc}."
    return str(exc)[:600] or type(exc).__name__


def parse_when(value: str | None, now: datetime) -> datetime:
    """`value` is an ISO datetime, "HH:MM" or nothing (now). A bare time means
    the latest such moment that is not in the future, so "23:30" said just
    after midnight is yesterday evening. Naive datetimes are local time."""
    now = now.astimezone(config.TZ)
    if value is None or not value.strip():
        return now
    m = _HHMM.match(value)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            raise ToolError(f"'{value}' is not a valid time; use HH:MM.")
        when = datetime.combine(now.date(), time(hour, minute), tzinfo=config.TZ)
        if when - now > _FUTURE_SLACK:
            when = datetime.combine(now.date() - timedelta(days=1), time(hour, minute), tzinfo=config.TZ)
        return when
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"'{value}' is not a time; use an ISO datetime or HH:MM.") from None
    parsed = parsed.replace(tzinfo=config.TZ) if parsed.tzinfo is None else parsed.astimezone(config.TZ)
    if parsed - now > _FUTURE_SLACK:
        raise ToolError(f"{parsed.isoformat(timespec='minutes')} is in the future; check the date.")
    return parsed


def _parse_day(value: str | None, today: date) -> date:
    if value is None or not value.strip():
        return today
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"'{value}' is not a date; use YYYY-MM-DD.") from None


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _nutrients(n: Nutrients) -> dict[str, float | None]:
    return {
        "kcal": _r(n.kcal),
        "protein_g": _r(n.protein_g),
        "fat_g": _r(n.fat_g),
        "carbs_g": _r(n.carbs_g),
        "fibre_g": _r(n.fibre_g),
    }


def _servings(servings: tuple[Serving, ...]) -> list[dict[str, Any]]:
    return [{"label": s.label, "grams": _r(s.grams)} for s in servings]


def _match_dict(ref: str, c: FoodCandidate) -> dict[str, Any]:
    return {
        "ref": ref,
        "name": c.name,
        "brand": c.brand,
        "source": c.source.value,
        "per_100g": _nutrients(c.per_100g),
        "servings": _servings(c.servings),
    }


def _entry_dict(e: Entry) -> dict[str, Any]:
    return {
        "id": e.id,
        "eaten_at": e.eaten_at.isoformat(timespec="minutes"),
        "name": e.name,
        "grams": _r(e.grams),
        "servings": _r(e.servings),
        "source": e.source.value,
        "confidence": e.confidence.value if e.confidence else None,
        "assumptions": e.assumptions,
        "nutrients": _nutrients(e.nutrients),
    }


def _goal_dict(s: GoalStatus) -> dict[str, Any]:
    g = s.goal
    out: dict[str, Any] = {
        "nutrient": g.nutrient,
        "kind": g.kind.value,
        "min": g.min,
        "max": g.max,
        "value": _r(s.value),
        "met": s.met,
    }
    # "remaining" is what is still missing to the minimum, "room" what is left
    # under the maximum.
    if g.min is not None and g.kind in (GoalKind.MIN, GoalKind.BAND):
        out["remaining"] = _r(max(g.min - s.value, 0.0))
    if g.max is not None and g.kind in (GoalKind.MAX, GoalKind.BAND):
        out["room"] = _r(max(g.max - s.value, 0.0))
    return out


class EstimateItem(BaseModel):
    name: str = Field(description="What is on the plate, in the user's words, e.g. 'Linsen-Dal'.")
    search_name: str = Field(
        description="A plain German food name to look up, e.g. 'Linse reif, gekocht' or 'Tofu'."
    )
    grams: float = Field(gt=0, description="Estimated weight of this item in grams.")
    confidence: Literal["high", "medium", "low"] = Field(
        description="How sure you are about the weight and the food."
    )
    assumptions: str = Field(
        default="", description="What you assumed, e.g. 'cooked in a little oil, plate about 300 g'."
    )
    kcal_100g: float | None = Field(
        default=None, ge=0, description="Estimated kcal per 100 g. Only for foods a database cannot know."
    )
    protein_100g: float | None = Field(default=None, ge=0, description="Estimated protein g per 100 g.")
    fat_100g: float | None = Field(default=None, ge=0, description="Estimated fat g per 100 g.")
    carbs_100g: float | None = Field(default=None, ge=0, description="Estimated carbohydrates g per 100 g.")


def create_mcp(
    store: Store,
    lookup: Lookup,
    tandoor: TandoorClient | None = None,
    opengym: OpenGymClient | None = None,
    *,
    now: Callable[[], datetime] | None = None,
) -> MCPServer:
    """Build the server. `now` replaces the clock in tests."""
    mcp = MCPServer("snacky")

    def clock() -> datetime:
        return now() if now is not None else datetime.now(config.TZ)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "server": mcp.name, "build": os.environ.get("IMAGE_SHA", "")})

    def amount(food: Food, grams: float | None, serving: str | None) -> tuple[float, str | None]:
        """Grams to log and the serving label used, if any. Exactly one input."""
        if (grams is None) == (serving is None):
            raise ToolError("Give exactly one of grams or serving.")
        if grams is not None:
            if grams <= 0:
                raise ToolError("grams must be more than 0.")
            return grams, None
        wanted = serving.strip().casefold()
        for s in food.servings:
            if s.label.strip().casefold() == wanted:
                return s.grams, s.label
        known = ", ".join(f"'{s.label}' = {_r(s.grams)} g" for s in food.servings) or "none"
        raise ToolError(
            f"{food.name} has no serving '{serving}'. Known servings: {known}. "
            "Give grams, or add_serving first."
        )

    def log_food_entry(
        food: Food,
        grams: float | None,
        serving: str | None,
        eaten_at: str | None,
    ) -> dict[str, Any]:
        when = parse_when(eaten_at, clock())
        total_g, label = amount(food, grams, serving)
        entry = store.log_entry(
            name=food.name,
            nutrients=food.per_100g.for_grams(total_g),
            eaten_at=when,
            source=food.source,
            origin=Origin.CHAT,
            grams=total_g,
            food_id=food.id,
        )
        return finish(entry, food=food, serving=label)

    def finish(entry: Entry, **extra: Any) -> dict[str, Any]:
        """The entry, what it came from, and the day so far, so the assistant
        can answer "how much protein today" without another call."""
        day = store.day_summary(entry.eaten_at.astimezone(config.TZ).date())
        out: dict[str, Any] = {"logged": True, "entry": _entry_dict(entry)}
        food = extra.get("food")
        if food is not None:
            out["food"] = {
                "ref": f"food:{food.id}",
                "name": food.name,
                "brand": food.brand,
                "source": food.source.value,
            }
        if extra.get("serving"):
            out["serving"] = extra["serving"]
        out["day_so_far"] = {
            "date": day.day.isoformat(),
            "kcal": _r(day.totals.kcal),
            "protein_g": _r(day.totals.protein_g),
        }
        return out

    @mcp.tool()
    @guarded(LookupFailed, OffUnavailable, httpx.HTTPStatusError)
    async def search_food(
        query: Annotated[
            str, Field(description="Food name, German or English, e.g. 'Tofu' or 'Haferflocken'.")
        ],
        limit: Annotated[int, Field(ge=1, le=15, description="Most matches to return.")] = 5,
    ) -> dict:
        """Look a food up. Searches foods already stored, then the BLS database, then Open Food Facts
        when those give too few. Each match has a `ref` to pass to log_food or add_serving, its source
        and its nutrients per 100 g. Never invent nutrient values; use these."""
        matches, notes = await lookup.search_with_notes(query, limit)
        return {
            "query": query,
            "matches": [_match_dict(m.ref, m.candidate) for m in matches],
            "notes": notes,
        }

    @mcp.tool()
    @guarded(LookupFailed, OffUnavailable, httpx.HTTPStatusError, NotFound, ValueError)
    async def log_food(
        food_ref: Annotated[
            str, Field(description="A ref from search_food: food:<id>, bls:<code> or off:<barcode>.")
        ],
        grams: Annotated[
            float | None, Field(description="Amount eaten in grams. Give this or serving.")
        ] = None,
        serving: Annotated[
            str | None, Field(description="A serving label the food has, e.g. '1 Scoop'. Give this or grams.")
        ] = None,
        eaten_at: Annotated[
            str | None, Field(description="ISO datetime or HH:MM (local time). Empty means now.")
        ] = None,
    ) -> dict:
        """Log a food from a search_food ref. Exactly one of grams or serving. The numbers come from
        the food's database entry, and the result names the source."""
        food = await lookup.by_ref(food_ref)
        return log_food_entry(food, grams, serving, eaten_at)

    @mcp.tool()
    @guarded(LookupFailed, OffUnavailable, httpx.HTTPStatusError, NotFound, ValueError)
    async def log_barcode(
        barcode: Annotated[str, Field(description="The product barcode digits (EAN/UPC).")],
        grams: Annotated[
            float | None, Field(description="Amount eaten in grams. Give this or serving.")
        ] = None,
        serving: Annotated[
            str | None, Field(description="A serving label the product has. Give this or grams.")
        ] = None,
        eaten_at: Annotated[
            str | None, Field(description="ISO datetime or HH:MM (local time). Empty means now.")
        ] = None,
    ) -> dict:
        """Log a packaged product by barcode. Looks it up in Open Food Facts (or a label stored earlier)
        and logs it. If the product is unknown, read its nutrition label and use log_label."""
        code = barcode.strip()
        if not code.isdigit() or not 6 <= len(code) <= 14:
            raise ToolError("A barcode is 6 to 14 digits.")
        food = await lookup.barcode(code)
        if food is None:
            raise ToolError(
                f"Open Food Facts has no usable product for barcode {code}. "
                "Read the nutrition label from a photo and use log_label instead."
            )
        return log_food_entry(food, grams, serving, eaten_at)

    @mcp.tool()
    @guarded(LookupFailed, NotFound, ValueError)
    async def log_label(
        name: Annotated[str, Field(description="Product name as printed.")],
        kcal_100g: Annotated[
            float, Field(ge=0, le=1000, description="kcal per 100 g, from the label's per-100 g column.")
        ],
        protein_100g: Annotated[float, Field(ge=0, le=100, description="Protein g per 100 g.")],
        fat_100g: Annotated[float, Field(ge=0, le=100, description="Fat g per 100 g.")],
        carbs_100g: Annotated[float, Field(ge=0, le=100, description="Carbohydrates g per 100 g.")],
        fibre_100g: Annotated[
            float | None, Field(ge=0, le=100, description="Fibre g per 100 g, if printed.")
        ] = None,
        brand: Annotated[str | None, Field(description="Brand as printed.")] = None,
        barcode: Annotated[
            str | None, Field(description="Barcode digits, if visible. Lets a later scan find this label.")
        ] = None,
        serving_label: Annotated[
            str | None, Field(description="A serving named on the pack, e.g. '1 Scoop'. Needs serving_grams.")
        ] = None,
        serving_grams: Annotated[float | None, Field(gt=0, description="Grams in that serving.")] = None,
        grams: Annotated[
            float | None, Field(description="Amount eaten in grams. Give this or serving.")
        ] = None,
        serving: Annotated[
            str | None,
            Field(description="A serving label, e.g. the serving_label just given. Give this or grams."),
        ] = None,
        eaten_at: Annotated[
            str | None, Field(description="ISO datetime or HH:MM (local time). Empty means now.")
        ] = None,
    ) -> dict:
        """Store a product from a photographed nutrition label, then log it. Use the per-100 g column
        exactly as printed; never use this for values you estimated. The food is stored with source
        'label' so it is found by name next time."""
        if (serving_label is None) != (serving_grams is None):
            raise ToolError("serving_label and serving_grams go together.")
        if protein_100g + fat_100g + carbs_100g > 105:
            raise ToolError(
                "Protein, fat and carbohydrates add up to more than 100 g per 100 g. "
                "Read the per-100 g column, not the per-serving one."
            )
        code = None
        if barcode is not None and barcode.strip():
            code = barcode.strip()
            if not code.isdigit() or not 6 <= len(code) <= 14:
                raise ToolError("A barcode is 6 to 14 digits.")
        per_100g = Nutrients(kcal_100g, protein_100g, fat_100g, carbs_100g, fibre_100g)
        servings = (Serving(serving_label.strip(), serving_grams),) if serving_label and serving_grams else ()
        brand = brand.strip() or None if brand else None
        candidate = FoodCandidate(
            name=name.strip(),
            source=Source.LABEL,
            per_100g=per_100g,
            source_ref=code,
            brand=brand,
            servings=servings,
        )
        existing = None
        if code is None:
            # Without a barcode nothing identifies the product, so the same
            # reading is reused instead of stored again.
            for food in store.search_foods(candidate.name, 20):
                if (
                    food.source is Source.LABEL
                    and food.source_ref is None
                    and food.name == candidate.name
                    and food.brand == brand
                    and food.per_100g == per_100g
                ):
                    existing = food
                    break
        food = existing or store.upsert_food(candidate)
        if existing is not None:
            for s in servings:
                food = store.add_serving(food.id, s)
        return log_food_entry(food, grams, serving, eaten_at)

    @mcp.tool()
    @guarded(TandoorError, NotFound, ValueError)
    async def log_recipe_portion(
        recipe_id: Annotated[int, Field(description="Tandoor recipe id.")],
        servings: Annotated[float, Field(gt=0, description="How many servings were eaten, e.g. 1.5.")],
        cooklog_id: Annotated[
            int | None,
            Field(description="Tandoor cook log id. The same cook log is never logged twice."),
        ] = None,
        eaten_at: Annotated[
            str | None, Field(description="ISO datetime or HH:MM (local time). Empty means now.")
        ] = None,
    ) -> dict:
        """Log portions of a Tandoor recipe. The nutrition is Tandoor's own, per serving. If the recipe
        has ingredients without nutrient data, nothing is logged and the missing ingredients are listed."""
        if tandoor is None:
            raise ToolError("Tandoor is not configured on this server.")
        when = parse_when(eaten_at, clock())
        recipe = await tandoor.recipe_nutrition(recipe_id)
        if not recipe.complete:
            return {
                "logged": False,
                "reason": "incomplete_recipe",
                "message": (
                    f"'{recipe.name}' was not logged: Tandoor has no nutrient data for some ingredients, "
                    "so the numbers would be too low. Add their nutrients in Tandoor first."
                ),
                "missing_ingredients": list(recipe.missing),
            }
        ref = f"tandoor-cooklog:{cooklog_id}" if cooklog_id is not None else None
        try:
            entry = store.log_entry(
                name=recipe.name,
                nutrients=recipe.per_serving.scaled(servings),
                eaten_at=when,
                source=Source.TANDOOR,
                # A cook log means the evening check found this meal in Tandoor.
                origin=Origin.TANDOOR if ref else Origin.CHAT,
                servings=servings,
                origin_ref=ref,
            )
        except DuplicateEntry:
            return {
                "logged": False,
                "reason": "already_logged",
                "message": f"Cook log {cooklog_id} of '{recipe.name}' is already logged. Nothing was added.",
            }
        out = finish(entry)
        out["recipe"] = {"id": recipe.recipe_id, "name": recipe.name, "source": Source.TANDOOR.value}
        return out

    @mcp.tool()
    @guarded(LookupFailed, NotFound, ValueError)
    async def log_estimate(
        items: Annotated[
            list[EstimateItem], Field(min_length=1, max_length=30, description="The items on the plate.")
        ],
        eaten_at: Annotated[
            str | None, Field(description="ISO datetime or HH:MM (local time). Empty means now.")
        ] = None,
    ) -> dict:
        """Log a meal from a plate photo. For each item the database is tried first with search_name (stored
        foods, then BLS), and its nutrients are used when the name matches. Only when nothing matches are
        your per-100 g estimates logged, stored as an estimate. An item with neither a match nor estimates
        is refused. This is shown to the user for approval before it runs."""
        when = parse_when(eaten_at, clock())
        results: list[dict[str, Any]] = []
        for item in items:
            confidence = Confidence(item.confidence)
            assumptions = item.assumptions.strip() or None
            food = None
            for match in lookup.search_local(item.search_name, 3):
                if is_good_match(item.search_name, match.candidate.name):
                    food = await lookup.by_ref(match.ref)
                    break
            if food is not None:
                entry = store.log_entry(
                    name=food.name,
                    nutrients=food.per_100g.for_grams(item.grams),
                    eaten_at=when,
                    source=food.source,
                    origin=Origin.CHAT,
                    grams=item.grams,
                    food_id=food.id,
                    confidence=confidence,
                    assumptions=assumptions,
                )
                results.append(
                    {
                        "item": item.name,
                        "logged": True,
                        "basis": "database",
                        "food": food.name,
                        "entry": _entry_dict(entry),
                    }
                )
                continue
            if item.kcal_100g is None or item.protein_100g is None:
                results.append(
                    {
                        "item": item.name,
                        "logged": False,
                        "reason": (
                            f"No stored or BLS food matches '{item.search_name}' and no kcal and protein "
                            "estimate was given. Try search_food for a better name, or resend "
                            "with per-100 g estimates."
                        ),
                    }
                )
                continue
            per_100g = Nutrients(
                kcal=item.kcal_100g,
                protein_g=item.protein_100g,
                fat_g=item.fat_100g or 0.0,
                carbs_g=item.carbs_100g or 0.0,
            )
            note = assumptions
            if item.fat_100g is None or item.carbs_100g is None:
                note = "; ".join(
                    filter(None, [assumptions, "fat or carbohydrates not estimated, counted as 0"])
                )
            entry = store.log_entry(
                name=item.name,
                nutrients=per_100g.for_grams(item.grams),
                eaten_at=when,
                source=Source.AI_ESTIMATE,
                origin=Origin.CHAT,
                grams=item.grams,
                confidence=confidence,
                assumptions=note,
            )
            results.append(
                {"item": item.name, "logged": True, "basis": "estimate", "entry": _entry_dict(entry)}
            )
        logged = [r for r in results if r["logged"]]
        out: dict[str, Any] = {"items": results, "logged": len(logged), "refused": len(results) - len(logged)}
        if logged:
            day = store.day_summary(when.date())
            out["day_so_far"] = {
                "date": day.day.isoformat(),
                "kcal": _r(day.totals.kcal),
                "protein_g": _r(day.totals.protein_g),
                "estimated_share": round(day.estimated_share, 2),
            }
        return out

    @mcp.tool()
    @guarded(NotFound, ValueError)
    async def day_summary(
        date: Annotated[str | None, Field(description="YYYY-MM-DD. Empty means today.")] = None,
    ) -> dict:
        """One day: totals, each goal with met and remaining, and the meals with their protein and entries
        (with ids for update_entry and delete_entry). estimated_share is the share of the day's kcal that
        came from estimates rather than a database."""
        day = _parse_day(date, clock().astimezone(config.TZ).date())
        s = store.day_summary(day)
        return {
            "date": s.day.isoformat(),
            "totals": _nutrients(s.totals),
            "goals": [_goal_dict(g) for g in s.goals],
            "estimated_share": round(s.estimated_share, 2),
            "meals": [
                {
                    "start": m.start.strftime("%H:%M"),
                    "kcal": _r(m.totals.kcal),
                    "protein_g": _r(m.totals.protein_g),
                    "entries": [_entry_dict(e) for e in m.entries],
                }
                for m in s.meals
            ],
        }

    @mcp.tool()
    @guarded(NotFound, ValueError)
    async def week_summary(
        start: Annotated[
            str | None,
            Field(description="First day, YYYY-MM-DD. Empty means the last seven days ending today."),
        ] = None,
    ) -> dict:
        """Seven days from `start` with totals and goal status per day. When openGym is set up it also
        lists the training days and body weights of that week."""
        today = clock().astimezone(config.TZ).date()
        first = _parse_day(start, today - timedelta(days=6))
        days = store.week_summary(first)
        out: dict[str, Any] = {
            "start": first.isoformat(),
            "end": (first + timedelta(days=6)).isoformat(),
        }
        notes: list[str] = []
        workouts = weights = None
        if opengym is not None:
            try:
                end = first + timedelta(days=7)
                workouts = await opengym.workouts_between(first, end)
                weights = await opengym.body_weights_between(first, end)
            except OpenGymError as exc:
                workouts = weights = None
                notes.append(f"Training days and body weight are left out: {exc}")
        trained = {w.day for w in workouts or []}
        rows = []
        for s in days:
            row: dict[str, Any] = {
                "date": s.day.isoformat(),
                "totals": _nutrients(s.totals),
                "estimated_share": round(s.estimated_share, 2),
                "goals": [{"nutrient": g.goal.nutrient, "value": _r(g.value), "met": g.met} for g in s.goals],
                "entries": sum(len(m.entries) for m in s.meals),
            }
            if workouts is not None:
                row["training"] = s.day in trained
            rows.append(row)
        out["days"] = rows
        logged = [s for s in days if s.meals]
        out["days_logged"] = len(logged)
        if logged:
            out["average_per_logged_day"] = {
                "kcal": _r(sum(s.totals.kcal for s in logged) / len(logged)),
                "protein_g": _r(sum(s.totals.protein_g for s in logged) / len(logged)),
            }
        if workouts is not None:
            out["workouts"] = [
                {"date": w.day.isoformat(), "name": w.name, "duration_min": w.duration_min} for w in workouts
            ]
            out["body_weights"] = [{"date": b.day.isoformat(), "kg": b.kg} for b in weights or []]
        out["notes"] = notes
        return out

    @mcp.tool()
    @guarded(NotFound, ValueError)
    async def update_entry(
        entry_id: Annotated[int, Field(description="Entry id from day_summary.")],
        grams: Annotated[
            float | None, Field(description="New amount in grams; the nutrients scale with it.")
        ] = None,
        servings: Annotated[
            float | None, Field(description="New number of servings, for a recipe portion.")
        ] = None,
        eaten_at: Annotated[
            str | None, Field(description="New time: ISO datetime or HH:MM (local time).")
        ] = None,
    ) -> dict:
        """Correct an entry's amount or time. A new amount rescales its nutrients in proportion."""
        if grams is None and servings is None and eaten_at is None:
            raise ToolError("Give grams, servings or eaten_at to change.")
        when = parse_when(eaten_at, clock()) if eaten_at else None
        entry = store.update_entry(entry_id, grams=grams, servings=servings, eaten_at=when)
        return {"updated": True, "entry": _entry_dict(entry)}

    @mcp.tool()
    @guarded(NotFound)
    async def delete_entry(entry_id: Annotated[int, Field(description="Entry id from day_summary.")]) -> dict:
        """Delete one log entry."""
        entry = store.get_entry(entry_id)
        store.delete_entry(entry_id)
        return {"deleted": True, "entry": _entry_dict(entry)}

    @mcp.tool()
    @guarded(ValueError)
    async def set_goal(
        nutrient: Annotated[NutrientName, Field(description="Which nutrient the daily goal is for.")],
        kind: Annotated[
            Literal["min", "max", "band"],
            Field(description="min: at least; max: at most; band: between min and max."),
        ],
        min: Annotated[float | None, Field(ge=0, description="Lower bound, for min and band.")] = None,
        max: Annotated[float | None, Field(ge=0, description="Upper bound, for max and band.")] = None,
        valid_from: Annotated[
            str | None,
            Field(description="First day it applies, YYYY-MM-DD. Empty means today. Older days keep theirs."),
        ] = None,
    ) -> dict:
        """Set a daily goal that applies from a date on. A goal for the same nutrient and date replaces
        the earlier one."""
        day = _parse_day(valid_from, clock().astimezone(config.TZ).date())
        goal = Goal(nutrient=nutrient, kind=GoalKind(kind), valid_from=day, min=min, max=max)
        store.set_goal(goal)
        return {
            "saved": True,
            "goal": {
                "nutrient": nutrient,
                "kind": kind,
                "min": min,
                "max": max,
                "valid_from": day.isoformat(),
            },
        }

    @mcp.tool()
    @guarded(LookupFailed, OffUnavailable, httpx.HTTPStatusError, NotFound, ValueError)
    async def add_serving(
        food_ref: Annotated[str, Field(description="A ref from search_food.")],
        label: Annotated[str, Field(description="Serving name, e.g. '1 Scoop'.")],
        grams: Annotated[float, Field(gt=0, description="Grams in one such serving.")],
    ) -> dict:
        """Teach a food a named serving, e.g. '1 Scoop' = 30 g, so log_food can use it. The same label
        again updates the grams."""
        label = label.strip()
        if not label:
            raise ToolError("label is empty.")
        food = await lookup.by_ref(food_ref)
        food = store.add_serving(food.id, Serving(label, grams))
        return {
            "saved": True,
            "food": {"ref": f"food:{food.id}", "name": food.name, "source": food.source.value},
            "servings": _servings(food.servings),
        }

    @mcp.tool()
    @guarded(NotFound, ValueError)
    async def suggest_foods(
        protein_g: Annotated[float, Field(gt=0, description="Protein still missing today, in grams.")],
        kcal_max: Annotated[
            float | None,
            Field(gt=0, description="Most kcal one suggested portion may have. Empty means no limit."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=10, description="Most suggestions to return.")] = 3,
    ) -> dict:
        """Suggest foods that close a protein gap. Candidates come only from what the user has eaten in
        the last 30 days and from their quick items, never from a built-in list. Ranked by how often the
        food was eaten and by protein per kcal. Each suggestion has the usual portion and the share of
        the gap it closes. With no history the list is empty and the note says so."""
        since = clock() - timedelta(days=_SUGGEST_DAYS)
        seen: dict[int, list[float]] = {}
        for e in store.entries_between(since, clock() + _FUTURE_SLACK):
            if e.food_id is not None and e.grams:
                seen.setdefault(e.food_id, []).append(e.grams)
        quick = {q.food_id: q.grams for q in store.quick_items()}
        ranked: list[tuple[float, dict[str, Any]]] = []
        over_limit = 0
        for food_id in seen.keys() | quick.keys():
            try:
                food = store.get_food(food_id)
            except NotFound:
                continue
            times = len(seen.get(food_id, []))
            if food_id in seen:
                grams, basis = statistics.median(seen[food_id]), "median of what you logged"
            elif food_id in quick:
                grams, basis = quick[food_id], "quick item"
            n = food.per_100g.for_grams(grams)
            if n.protein_g <= 0:
                continue
            if kcal_max is not None and n.kcal > kcal_max:
                over_limit += 1
                continue
            label = next((sv.label for sv in food.servings if abs(sv.grams - grams) < 1), None)
            # A quick item counts as one more time eaten, so a pinned food that
            # was not logged this month still has a chance.
            weight = times + (1 if food_id in quick else 0)
            density = n.protein_g / max(n.kcal, 1.0)
            ranked.append(
                (
                    weight * density,
                    {
                        "ref": f"food:{food.id}",
                        "name": food.name,
                        "source": food.source.value,
                        "times_eaten": times,
                        "quick_item": food_id in quick,
                        "portion_g": _r(grams),
                        "portion_basis": basis,
                        "serving": label,
                        "kcal": _r(n.kcal),
                        "protein_g": _r(n.protein_g),
                        "protein_per_100kcal": _r(density * 100),
                        "closes_gap_pct": round(min(n.protein_g / protein_g, 1.0) * 100),
                    },
                )
            )
        ranked.sort(key=lambda r: (-r[0], r[1]["name"]))
        suggestions = [r[1] for r in ranked[:limit]]
        note = None
        if not seen and not quick:
            note = (
                f"Nothing eaten in the last {_SUGGEST_DAYS} days and no quick items, so there is nothing "
                "to suggest. Ask the user what they have at home."
            )
        elif not suggestions and over_limit:
            note = (
                f"Every usual portion has more than {kcal_max:g} kcal. "
                "Raise kcal_max or suggest a smaller portion."
            )
        return {"gap_protein_g": _r(protein_g), "suggestions": suggestions, "note": note}

    @mcp.tool()
    @guarded(NotFound, ValueError)
    async def log_again(
        entry_ids: Annotated[
            list[int],
            Field(min_length=1, max_length=30, description="Entry ids from day_summary to copy."),
        ],
        eaten_at: Annotated[
            str | None, Field(description="ISO datetime or HH:MM (local time). Empty means now.")
        ] = None,
    ) -> dict:
        """Log earlier entries again, e.g. 'the same breakfast as yesterday': get the ids from day_summary.
        Each copy keeps the original's food, grams and nutrients and gets the new time. Nothing is
        logged if one id does not exist."""
        when = parse_when(eaten_at, clock())
        originals = [store.get_entry(i) for i in entry_ids]
        copies = [
            store.log_entry(
                name=e.name,
                nutrients=e.nutrients,
                eaten_at=when,
                source=e.source,
                origin=Origin.CHAT,
                grams=e.grams,
                servings=e.servings,
                food_id=e.food_id,
                confidence=e.confidence,
                assumptions=e.assumptions,
                # origin_ref is unique and names one cook log, so a copy has none.
            )
            for e in originals
        ]
        day = store.day_summary(when.date())
        return {
            "logged": len(copies),
            "entries": [_entry_dict(e) for e in copies],
            "day_so_far": {
                "date": day.day.isoformat(),
                "kcal": _r(day.totals.kcal),
                "protein_g": _r(day.totals.protein_g),
            },
        }

    @mcp.tool()
    @guarded()
    async def recipe_nutrition(
        recipe_ids: Annotated[
            list[int], Field(min_length=1, max_length=20, description="Tandoor recipe ids, at most 20.")
        ],
    ) -> dict:
        """Nutrition per serving for Tandoor recipes, as Tandoor computes it: kcal, protein and protein per
        100 kcal, to rank recipes by protein when planning meals. A recipe with `complete` false has
        ingredients without nutrient data (listed in `missing`), so its numbers are too low. A recipe that
        fails is reported on its own and does not stop the others."""
        if tandoor is None:
            raise ToolError("Tandoor is not configured on this server.")
        recipes: list[dict[str, Any]] = []
        for recipe_id in dict.fromkeys(recipe_ids):
            try:
                r = await tandoor.recipe_nutrition(recipe_id)
            except TandoorError as exc:
                recipes.append({"recipe_id": recipe_id, "error": _describe(exc)})
                continue
            n = r.per_serving
            recipes.append(
                {
                    "recipe_id": r.recipe_id,
                    "name": r.name,
                    "servings": _r(r.servings),
                    "per_serving": _nutrients(n),
                    "protein_per_100kcal": _r(n.protein_g / n.kcal * 100) if n.kcal > 0 else None,
                    "complete": r.complete,
                    "missing": list(r.missing),
                    "source": Source.TANDOOR.value,
                }
            )
        return {"recipes": recipes}

    return mcp


def create_mcp_app(mcp: MCPServer) -> Starlette:
    """The ASGI app for `mcp`: stateless streamable HTTP with plain JSON answers.

    Stateless because the bot holds a session per server from startup and does
    not replay a call that fails after the SDK expires an idle session (30 min).
    Nothing here keeps state between calls. DNS-rebinding protection is off
    because it answers 421 to any Host but localhost, which is every request a
    Service or proxy delivers; only the assistant can reach this port.
    """
    return mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
