"""Tandoor (2.6.x): recipe nutrition for logging a portion, and food
properties for filling nutrients in from BLS.

Written against the Tandoor 2.6.15 source (github.com/TandoorRecipes/recipes,
tag 2.6.15), read without a live instance:

- cookbook/models.py: PropertyType (name, unit, fdc_id), Property
  (property_amount, property_type), FoodProperty (through table), Food
  (properties, properties_food_amount, properties_food_unit), Unit.
- cookbook/helper/property_helper.py: FoodPropertyHelper
  .calculate_recipe_properties, which builds a recipe's `food_properties`.
- cookbook/helper/unit_conversion_helper.py: base units and conversions.
- cookbook/serializer.py: PropertyTypeSerializer, PropertySerializer,
  FoodSerializer, RecipeSerializer.
- cookbook/views/api.py: DefaultPagination (page, page_size up to 200) and the
  property-type, food, unit and recipe viewsets.
- recipes/settings.py: OAuth2Authentication, so a token goes in
  `Authorization: Bearer <token>`.

What Tandoor computes: `food_properties` is a dict keyed by property type id.
Each entry has `total_value` for the WHOLE recipe (it is not divided by
servings) and `food_values`, one entry per food with `value`. A `value` of
None means the ingredient could not be converted to the food's property unit,
or the food has no value for that type. `missing_unit: true` marks an amount
without a unit. An ingredient with no amount counts as 0 and is not missing.
The entries carry no `fdc_id`, so the types come from /api/property-type/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from snacky.model import Nutrients, RecipeNutrition

# FoodData Central nutrient ids, keyed by the Nutrients field they fill.
FDC_IDS: dict[str, int] = {
    "kcal": 1008,
    "protein_g": 1003,
    "fat_g": 1004,
    "carbs_g": 1005,
    "fibre_g": 1079,
}

# Names and units used when snacky creates a missing property type. Tandoor
# keeps property types unique by name, so these must not collide with a
# differently named type the user already has.
DEFAULT_TYPES: dict[str, tuple[str, str]] = {
    "kcal": ("Kalorien", "kcal"),
    "protein_g": ("Eiweiß", "g"),
    "fat_g": ("Fett", "g"),
    "carbs_g": ("Kohlenhydrate", "g"),
    "fibre_g": ("Ballaststoffe", "g"),
}

# Fallback when a property type has no fdc_id. Compared case-insensitively.
NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "kcal": ("kalorien", "energie", "energy", "calories", "kcal", "brennwert"),
    "protein_g": ("protein", "proteine", "proteins", "eiweiß", "eiweiss"),
    "fat_g": ("fett", "fat", "total fat", "gesamtfett", "fette"),
    "carbs_g": ("kohlenhydrate", "carbohydrate", "carbohydrates", "carbs"),
    "fibre_g": ("ballaststoffe", "ballaststoff", "fibre", "fiber", "dietary fibre", "dietary fiber"),
}

REQUIRED = ("kcal", "protein_g", "fat_g", "carbs_g")
KJ_PER_KCAL = 4.184
PAGE_SIZE = 200  # DefaultPagination.max_page_size


class TandoorError(Exception):
    """A Tandoor request failed or returned something unusable."""


@dataclass(frozen=True)
class PropertyType:
    id: int
    name: str
    unit: str | None = None
    fdc_id: int | None = None


@dataclass(frozen=True)
class TandoorFood:
    id: int
    name: str
    # property type id -> amount, per `properties_food_amount` of the unit below
    properties: dict[int, float] = field(default_factory=dict)
    properties_food_amount: float = 100.0
    properties_food_unit: str | None = None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _to_type(raw: dict[str, Any]) -> PropertyType:
    return PropertyType(id=raw["id"], name=raw["name"], unit=raw.get("unit"), fdc_id=raw.get("fdc_id"))


def _to_food(raw: dict[str, Any]) -> TandoorFood:
    unit = raw.get("properties_food_unit") or None
    props: dict[int, float] = {}
    for p in raw.get("properties") or []:
        amount = _num(p.get("property_amount"))
        if amount is not None:
            props[p["property_type"]["id"]] = amount
    return TandoorFood(
        id=raw["id"],
        name=raw["name"],
        properties=props,
        properties_food_amount=_num(raw.get("properties_food_amount")) or 100.0,
        properties_food_unit=unit["name"] if unit else None,
    )


def map_types(types: list[PropertyType]) -> dict[str, PropertyType]:
    """Map Nutrients field names to property types. The fdc_id decides first,
    because users rename types; names only fill what the ids left open."""
    found: dict[str, PropertyType] = {}
    by_fdc = {v: k for k, v in FDC_IDS.items()}
    for t in types:
        key = by_fdc.get(t.fdc_id) if t.fdc_id is not None else None
        if key and key not in found:
            found[key] = t
    taken = {t.id for t in found.values()}
    for t in types:
        if t.id in taken:
            continue
        name = t.name.strip().casefold()
        for key, aliases in NAME_ALIASES.items():
            if key not in found and name in aliases:
                found[key] = t
                taken.add(t.id)
                break
    return found


class TandoorClient:
    def __init__(self, base_url: str, token: str, http: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base}{path}"
        try:
            resp = await self._http.request(method, url, headers=self._headers, **kwargs)
        except httpx.RequestError as e:
            raise TandoorError(f"Tandoor is unreachable ({method} {path}): {e.__class__.__name__}") from e
        if resp.status_code >= 400:
            hint = " Check the token and its read/write scope." if resp.status_code in (401, 403) else ""
            raise TandoorError(
                f"Tandoor answered {resp.status_code} for {method} {path}.{hint} {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise TandoorError(f"Tandoor sent a non-JSON answer for {method} {path}") from e

    async def _pages(self, path: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            data = await self._request("GET", path, params={"page": page, "page_size": PAGE_SIZE})
            out.extend(data.get("results", []))
            # Follow the page counter, not `next`: that link carries the
            # server's own idea of its host name.
            if not data.get("next"):
                return out
            page += 1

    async def property_types(self) -> list[PropertyType]:
        return [_to_type(t) for t in await self._pages("/api/property-type/")]

    async def ensure_property_types(self) -> dict[str, PropertyType]:
        """The five nutrient types keyed by Nutrients field name. Creates only
        the ones Tandoor lacks, matched by fdc_id or name."""
        found = map_types(await self.property_types())
        for key, fdc in FDC_IDS.items():
            if key in found:
                continue
            name, unit = DEFAULT_TYPES[key]
            raw = await self._request(
                "POST", "/api/property-type/", json={"name": name, "unit": unit, "fdc_id": fdc}
            )
            found[key] = _to_type(raw)
        return found

    async def list_foods(self) -> list[TandoorFood]:
        return [_to_food(f) for f in await self._pages("/api/food/")]

    async def _gram_unit(self) -> dict[str, Any]:
        for u in await self._pages("/api/unit/"):
            if (u.get("name") or "").strip().casefold() in ("g", "gramm", "gram"):
                return u
        # base_unit "g" is what lets Tandoor convert kg or oz ingredients to it.
        return await self._request(
            "POST", "/api/unit/", json={"name": "g", "plural_name": "g", "base_unit": "g"}
        )

    async def set_food_properties(self, food_id: int, per_100g: Nutrients) -> TandoorFood:
        """Write the nutrient values for 100 g of the food. Tandoor replaces a
        food's whole property list on save, so existing properties are sent
        back: our types by id with the new amount, every other type untouched."""
        types = await self.ensure_property_types()
        raw_food = await self._request("GET", f"/api/food/{food_id}/")
        existing: dict[int, dict[str, Any]] = {
            p["property_type"]["id"]: p for p in raw_food.get("properties") or []
        }
        values = {
            "kcal": per_100g.kcal,
            "protein_g": per_100g.protein_g,
            "fat_g": per_100g.fat_g,
            "carbs_g": per_100g.carbs_g,
            "fibre_g": per_100g.fibre_g,
        }
        wanted = {types[k].id: round(v, 4) for k, v in values.items() if v is not None}

        properties: list[dict[str, Any]] = []
        for type_id, prop in existing.items():
            if type_id in wanted:
                prop = {**prop, "property_amount": wanted.pop(type_id)}
            properties.append(prop)
        for t in types.values():
            if t.id in wanted:
                properties.append(
                    {
                        "property_amount": wanted[t.id],
                        "property_type": {"id": t.id, "name": t.name, "unit": t.unit, "fdc_id": t.fdc_id},
                    }
                )

        payload = {
            "properties_food_amount": 100,
            "properties_food_unit": await self._gram_unit(),
            "properties": properties,
        }
        return _to_food(await self._request("PATCH", f"/api/food/{food_id}/", json=payload))

    async def recipe_nutrition(self, recipe_id: int) -> RecipeNutrition:
        """Nutrition per serving as Tandoor computes it from its food properties."""
        recipe = await self._request("GET", f"/api/recipe/{recipe_id}/")
        mapped = map_types(await self.property_types())
        absent = [k for k in REQUIRED if k not in mapped]
        if absent:
            raise TandoorError(
                f"Tandoor has no property type for: {', '.join(absent)}. Run ensure_property_types."
            )

        servings = _num(recipe.get("servings")) or 1.0
        computed = recipe.get("food_properties") or {}
        missing: list[str] = []
        totals: dict[str, float | None] = {}

        for key, t in mapped.items():
            entry = computed.get(str(t.id)) or computed.get(t.id)
            if entry is None:
                # The type exists but the recipe has no entry for it, which
                # happens when the type was created after the recipe was cached.
                totals[key] = None
                continue
            total = _num(entry.get("total_value")) or 0.0
            if key == "kcal" and (t.unit or "").strip().casefold() == "kj":
                total /= KJ_PER_KCAL
            totals[key] = total
            incomplete = False
            for fv in (entry.get("food_values") or {}).values():
                if fv.get("value") is None or fv.get("missing_unit"):
                    incomplete = True
                    if key in REQUIRED:
                        name = (fv.get("food") or {}).get("name", "unknown food")
                        if name not in missing:
                            missing.append(name)
            # Fibre is optional in Nutrients, so a gap there only blanks fibre.
            if key == "fibre_g" and (incomplete or entry.get("missing_value")):
                totals[key] = None

        if any(totals.get(k) is None for k in REQUIRED):
            raise TandoorError(
                f"Recipe {recipe_id} has no computed value for a nutrient; open it in Tandoor once."
            )

        fibre = totals.get("fibre_g")
        per_serving = Nutrients(
            kcal=totals["kcal"] / servings,
            protein_g=totals["protein_g"] / servings,
            fat_g=totals["fat_g"] / servings,
            carbs_g=totals["carbs_g"] / servings,
            fibre_g=None if fibre is None else fibre / servings,
        )
        return RecipeNutrition(
            recipe_id=recipe_id,
            name=recipe.get("name", ""),
            servings=servings,
            per_serving=per_serving,
            complete=not missing,
            missing=tuple(missing),
        )
