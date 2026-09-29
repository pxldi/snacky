"""Routes for the web UI and its JSON API.

Pages are server-rendered and every form works without JavaScript. The store
is called directly from the handlers: it is one SQLite file behind a lock and
each call takes well under a millisecond.
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
import os
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from snacky import config
from snacky.model import Origin
from snacky.sources.opengym import OpenGymClient
from snacky.store import NotFound, Store
from snacky.web import format as fmt

_HERE = Path(__file__).parent
_OPENGYM_TIMEOUT_S = 5
# How long after logging from the web UI the undo button still works. Later
# on, a stale link or a second tab could delete an entry the user meant to keep.
_UNDO_WINDOW = timedelta(seconds=120)
_UNDO_STALE = (
    "Rückgängig geht nur kurz nach dem Eintragen in der Weboberfläche. "
    "Lösche den Eintrag sonst über die Bearbeitung."
)


# Nothing loads from outside this origin and nothing runs inline, so the
# policy can be this strict.
_CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


class _Rejected(Exception):
    """A request the user got wrong. The message is shown as is."""


def _now() -> datetime:
    return datetime.now(config.TZ)


def _today() -> date:
    return _now().date()


# Parsing


def _day_arg(value: str | None, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "Ungültiges Datum, erwartet JJJJ-MM-TT.") from None


def _positive(value: Any, label: str) -> float:
    try:
        number = float(str(value).strip().replace(",", "."))
    except ValueError:
        raise _Rejected(f"{label}: keine Zahl.") from None
    if not math.isfinite(number) or number <= 0:
        raise _Rejected(f"{label} muss größer als null sein.")
    return number


def _int(value: Any, label: str) -> int:
    try:
        return int(str(value).strip())
    except ValueError:
        raise _Rejected(f"{label}: keine ganze Zahl.") from None


async def _form(request: Request) -> dict[str, str]:
    # Parsed by hand: Starlette's form parser needs python-multipart, which
    # this app does not otherwise use.
    parsed = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _safe_next(value: str | None, fallback: str) -> str:
    """Only paths on this site, so a form cannot redirect elsewhere."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return fallback


def _combine(day_text: str, time_text: str) -> datetime:
    try:
        return datetime.combine(date.fromisoformat(day_text), time.fromisoformat(time_text), tzinfo=config.TZ)
    except ValueError:
        raise _Rejected("Datum oder Uhrzeit ist ungültig.") from None


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def _meal_min() -> float | None:
    raw = os.environ.get("SNACKY_MEAL_PROTEIN_MIN", "").strip()
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


# Middleware


class _Guard(BaseHTTPMiddleware):
    """Rejects cross-site writes and sets the security headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in ("GET", "HEAD") and not self._same_site(request):
            response: Response = PlainTextResponse("Cross-site request rejected.", status_code=403)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @staticmethod
    def _same_site(request: Request) -> bool:
        if request.headers.get("sec-fetch-site") == "same-origin":
            return True
        origin = request.headers.get("origin")
        if not origin:
            return False
        hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")} - {None}
        return urlsplit(origin).netloc in hosts


def create_app(store: Store, *, opengym: OpenGymClient | None = None) -> Starlette:
    """The web app. `opengym` marks training days in the week view when set."""
    env = Environment(
        loader=FileSystemLoader(_HERE / "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(upfirst=fmt.upfirst, num=fmt.num, amount=fmt.amount, input_number=fmt.input_number)
    env.globals.update(
        date_long=fmt.date_long,
        date_short=fmt.date_short,
        clock=fmt.clock,
        is_estimate=fmt.is_estimate,
        SOURCE_LABELS=fmt.SOURCE_LABELS,
        CONFIDENCE_LABELS=fmt.CONFIDENCE_LABELS,
        ORIGIN_LABELS=fmt.ORIGIN_LABELS,
        NUTRIENT_LABELS=fmt.NUTRIENT_LABELS,
        AI_ESTIMATE=fmt.Source.AI_ESTIMATE,
    )

    def render(request: Request, name: str, status: int = 200, **context: Any) -> HTMLResponse:
        page = env.get_template(name).render(path=request.url.path, **context)
        return HTMLResponse(page, status_code=status)

    def is_api(request: Request) -> bool:
        return request.url.path.startswith("/api/")

    def undoable(entry: Any) -> bool:
        age = _now() - entry.eaten_at
        return entry.origin is Origin.UI and timedelta(0) <= age < _UNDO_WINDOW

    def undo_entry(request: Request) -> Any:
        """The entry `?undo=` names, when it may still be undone; else None."""
        undo_id = request.query_params.get("undo", "")
        if not (undo_id.isascii() and undo_id.isdigit()):
            return None
        try:
            entry = store.get_entry(int(undo_id))
        except NotFound:
            return None
        return entry if undoable(entry) else None

    # Pages

    async def day_page(request: Request) -> Response:
        today = _today()
        day = _day_arg(request.query_params.get("day"), today)
        summary = store.day_summary(day)
        by_nutrient = {status.goal.nutrient: status for status in summary.goals}
        meal_min = _meal_min()
        meals = [
            {
                "meal": meal,
                "reached": None if meal_min is None else meal.totals.protein_g >= meal_min,
            }
            for meal in summary.meals
        ]
        quick = []
        if day == today:
            for item in store.quick_items():
                food = store.get_food(item.food_id)
                quick.append({"item": item, "nutrients": food.per_100g.for_grams(item.grams)})
        undo = undo_entry(request)
        return render(
            request,
            "day.html",
            summary=summary,
            day=day,
            today=today,
            prev_day=day - timedelta(days=1),
            next_day=day + timedelta(days=1),
            protein=fmt.goal_view(by_nutrient.get("protein_g"), "g"),
            kcal=fmt.goal_view(by_nutrient.get("kcal"), "kcal"),
            meals=meals,
            meal_min=meal_min,
            quick=quick,
            undo=undo,
        )

    async def week_page(request: Request) -> Response:
        today = _today()
        start = _day_arg(request.query_params.get("start"), fmt.week_start(today))
        end = start + timedelta(days=6)
        rows, workouts, failed = await _week(start)
        scale = max([1.0] + [r["protein"] for r in rows] + [r["limit"] or 0 for r in rows])
        for row in rows:
            row["fill"] = row["protein"] / scale * 100
            row["goal_x"] = None if not row["limit"] else row["limit"] / scale * 100
            row["training"] = workouts.get(row["day"], [])
        logged = [r["protein"] for r in rows if r["kcal"] > 0]
        return render(
            request,
            "week.html",
            start=start,
            end=end,
            today=today,
            prev_start=start - timedelta(days=7),
            next_start=start + timedelta(days=7),
            rows=rows,
            average=sum(logged) / len(logged) if logged else None,
            opengym_failed=failed,
            has_opengym=opengym is not None,
        )

    async def _week(start: date) -> tuple[list[dict], dict[date, list], bool]:
        rows = []
        for summary in store.week_summary(start):
            protein = next((s for s in summary.goals if s.goal.nutrient == "protein_g"), None)
            view = fmt.goal_view(protein, "g")
            rows.append(
                {
                    "day": summary.day,
                    "protein": summary.totals.protein_g,
                    "kcal": summary.totals.kcal,
                    "met": bool(view and view["met"]),
                    "limit": view["limit"] if view else None,
                    "has_goal": view is not None,
                    "count": sum(len(m.entries) for m in summary.meals),
                }
            )
        workouts: dict[date, list] = {}
        failed = False
        if opengym is not None:
            try:
                found = await asyncio.wait_for(
                    opengym.workouts_between(start, start + timedelta(days=7)), _OPENGYM_TIMEOUT_S
                )
                for workout in found:
                    workouts.setdefault(workout.day, []).append(workout)
            except Exception:
                # Training markers are a nicety; the week must render without them.
                failed = True
        return rows, workouts, failed

    async def entry_page(request: Request) -> Response:
        entry = store.get_entry(request.path_params["entry_id"])
        return render(request, "edit.html", entry=entry, back=_back(request, entry))

    def _back(request: Request, entry: Any) -> str:
        return _safe_next(request.query_params.get("back"), f"/?day={entry.eaten_at.date().isoformat()}")

    async def entry_update(request: Request) -> Response:
        entry_id = request.path_params["entry_id"]
        entry = store.get_entry(entry_id)
        form = await _form(request)
        back = _safe_next(form.get("back"), f"/?day={entry.eaten_at.date().isoformat()}")
        try:
            eaten_at = _combine(form.get("day", ""), form.get("time", ""))
            grams = servings = None
            if "amount" in form:
                amount = _positive(form["amount"], "Menge")
                if entry.grams:
                    grams = amount
                else:
                    servings = amount
            store.update_entry(entry_id, grams=grams, servings=servings, eaten_at=eaten_at)
        except (_Rejected, ValueError) as exc:
            return render(request, "edit.html", 400, entry=entry, back=back, error=str(exc), form=form)
        return RedirectResponse(_safe_next(back, "/"), status_code=303)

    async def entry_delete_page(request: Request) -> Response:
        entry = store.get_entry(request.path_params["entry_id"])
        return render(request, "delete.html", entry=entry, back=_back(request, entry))

    async def entry_delete(request: Request) -> Response:
        entry = store.get_entry(request.path_params["entry_id"])
        form = await _form(request)
        store.delete_entry(entry.id)
        return RedirectResponse(
            _safe_next(form.get("next"), f"/?day={entry.eaten_at.date().isoformat()}"), status_code=303
        )

    def quick_page_response(request: Request, status: int = 200, error: str | None = None) -> Response:
        query = request.query_params.get("q", "").strip()
        items = []
        for item in store.quick_items():
            food = store.get_food(item.food_id)
            items.append({"item": item, "food": food, "nutrients": food.per_100g.for_grams(item.grams)})
        results = store.search_foods(query, limit=8) if query else []
        return render(
            request,
            "quick.html",
            status,
            items=items,
            query=query,
            results=results,
            error=error,
            undo=undo_entry(request),
        )

    async def quick_page(request: Request) -> Response:
        return quick_page_response(request)

    async def quick_add(request: Request) -> Response:
        form = await _form(request)
        try:
            food = store.get_food(_int(form.get("food_id"), "Lebensmittel"))
            grams = _positive(form.get("grams", ""), "Menge")
        except NotFound:
            raise HTTPException(404, "Lebensmittel nicht gefunden.") from None
        except _Rejected as exc:
            return quick_page_response(request, 400, str(exc))
        store.add_quick_item(food.id, grams, form.get("label", "").strip() or food.name)
        return RedirectResponse("/quick", status_code=303)

    async def quick_remove(request: Request) -> Response:
        store.remove_quick_item(request.path_params["item_id"])
        return RedirectResponse("/quick", status_code=303)

    def _log_quick(item_id: int):
        item = next((i for i in store.quick_items() if i.id == item_id), None)
        if item is None:
            raise NotFound(f"quick item {item_id}")
        food = store.get_food(item.food_id)
        return store.log_entry(
            name=food.name,
            nutrients=food.per_100g.for_grams(item.grams),
            eaten_at=_now(),
            source=food.source,
            origin=Origin.UI,
            grams=item.grams,
            food_id=food.id,
        )

    async def quick_log(request: Request) -> Response:
        form = await _form(request)
        entry = _log_quick(request.path_params["item_id"])
        # Only the two pages that show the undo notice may be returned to.
        back = form.get("next") if form.get("next") in ("/", "/quick") else "/"
        return RedirectResponse(f"{back}?undo={entry.id}", status_code=303)

    async def entry_undo(request: Request) -> Response:
        entry = store.get_entry(request.path_params["entry_id"])
        if not undoable(entry):
            raise HTTPException(409, _UNDO_STALE)
        form = await _form(request)
        store.delete_entry(entry.id)
        return RedirectResponse(_safe_next(form.get("next"), "/"), status_code=303)

    # JSON API

    async def api_day(request: Request) -> Response:
        day = _day_arg(request.query_params.get("day"), _today())
        return JSONResponse(_jsonable(store.day_summary(day)))

    async def api_week(request: Request) -> Response:
        start = _day_arg(request.query_params.get("start"), fmt.week_start(_today()))
        _, workouts, failed = await _week(start)
        return JSONResponse(
            {
                "start": start.isoformat(),
                "days": _jsonable(store.week_summary(start)),
                "training": _jsonable([w for day in sorted(workouts) for w in workouts[day]]),
                "training_available": opengym is not None and not failed,
            }
        )

    async def api_entry_update(request: Request) -> Response:
        body = await _json_object(request)
        entry_id = request.path_params["entry_id"]
        try:
            grams = _positive(body["grams"], "grams") if body.get("grams") is not None else None
            servings = _positive(body["servings"], "servings") if body.get("servings") is not None else None
            eaten_at = None
            if body.get("eaten_at") is not None:
                eaten_at = datetime.fromisoformat(str(body["eaten_at"]))
                if eaten_at.tzinfo is None:
                    eaten_at = eaten_at.replace(tzinfo=config.TZ)
            entry = store.update_entry(entry_id, grams=grams, servings=servings, eaten_at=eaten_at)
        except (_Rejected, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None
        return JSONResponse(_jsonable(entry))

    async def api_entry_delete(request: Request) -> Response:
        store.delete_entry(request.path_params["entry_id"])
        return JSONResponse({"deleted": request.path_params["entry_id"]})

    async def api_quick_list(request: Request) -> Response:
        return JSONResponse(_jsonable(store.quick_items()))

    async def api_quick_add(request: Request) -> Response:
        body = await _json_object(request)
        try:
            food = store.get_food(_int(body.get("food_id"), "food_id"))
            grams = _positive(body.get("grams"), "grams")
        except _Rejected as exc:
            raise HTTPException(422, str(exc)) from None
        label = str(body.get("label") or "").strip() or food.name
        return JSONResponse(_jsonable(store.add_quick_item(food.id, grams, label)), status_code=201)

    async def api_quick_remove(request: Request) -> Response:
        store.remove_quick_item(request.path_params["item_id"])
        return JSONResponse({"deleted": request.path_params["item_id"]})

    async def api_quick_log(request: Request) -> Response:
        return JSONResponse(_jsonable(_log_quick(request.path_params["item_id"])), status_code=201)

    async def api_foods(request: Request) -> Response:
        foods = store.search_foods(request.query_params.get("q", ""), limit=20)
        return JSONResponse(_jsonable(foods))

    async def _json_object(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Body is not valid JSON.") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "Body must be a JSON object.")
        return body

    # Errors

    async def http_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, HTTPException)
        if is_api(request):
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", exc.status_code, code=exc.status_code, message=exc.detail)

    async def not_found(request: Request, exc: Exception) -> Response:
        if is_api(request):
            return JSONResponse({"error": str(exc)}, status_code=404)
        return render(request, "error.html", 404, code=404, message="Nicht gefunden.")

    async def health(request: Request) -> Response:
        return PlainTextResponse("ok")

    async def favicon(request: Request) -> Response:
        return Response(status_code=204)

    routes = [
        Route("/", day_page),
        Route("/week", week_page),
        Route("/entries/{entry_id:int}", entry_page),
        Route("/entries/{entry_id:int}", entry_update, methods=["POST"]),
        Route("/entries/{entry_id:int}/delete", entry_delete_page),
        Route("/entries/{entry_id:int}/delete", entry_delete, methods=["POST"]),
        Route("/entries/{entry_id:int}/undo", entry_undo, methods=["POST"]),
        Route("/quick", quick_page),
        Route("/quick", quick_add, methods=["POST"]),
        Route("/quick/{item_id:int}/remove", quick_remove, methods=["POST"]),
        Route("/quick/{item_id:int}/log", quick_log, methods=["POST"]),
        Route("/api/day", api_day),
        Route("/api/week", api_week),
        Route("/api/entries/{entry_id:int}", api_entry_update, methods=["PATCH", "PUT"]),
        Route("/api/entries/{entry_id:int}", api_entry_delete, methods=["DELETE"]),
        Route("/api/quick", api_quick_list),
        Route("/api/quick", api_quick_add, methods=["POST"]),
        Route("/api/quick/{item_id:int}", api_quick_remove, methods=["DELETE"]),
        Route("/api/quick/{item_id:int}/log", api_quick_log, methods=["POST"]),
        Route("/api/foods", api_foods),
        Route("/health", health),
        Route("/favicon.ico", favicon),
        Mount("/static", StaticFiles(directory=_HERE / "static"), name="static"),
    ]
    return Starlette(
        routes=routes,
        middleware=[Middleware(_Guard)],
        exception_handlers={HTTPException: http_error, NotFound: not_found},
    )
