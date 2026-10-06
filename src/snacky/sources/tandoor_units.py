"""Gram conversions so Tandoor can count "1 Zwiebel" or "2 EL Olivenöl".

    python -m snacky.sources.tandoor_units suggest --out units.csv
    python -m snacky.sources.tandoor_units apply units.csv

Tandoor turns an ingredient into nutrients only when it can convert its amount
into the unit the food's values are per (grams here). Weights convert by
themselves, but Stück, EL, TL, Bund or Dose need a conversion for that food,
and an amount without any unit is never counted. One missing conversion leaves
the whole recipe incomplete, so Snacky refuses to log it.

`suggest` reads every recipe and writes one row per food and unit Tandoor
cannot convert, with a suggested weight for one unit: `food` when the table
below knows that food, `unit` for a generic guess, empty when there is no
sensible default. Amounts without a unit become Stück, and their ingredient
ids travel in the row so `apply` can set the unit. The reviewer checks or
edits the grams and puts `y` in `ok`, as in tandoor_match. `apply` writes only
those rows.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from snacky import config
from snacky.sources.tandoor import TandoorClient, TandoorError

COLUMNS = ["food_id", "food_name", "unit", "grams", "basis", "recipes", "ingredient_ids", "ok"]

PIECE = "Stück"
_WEIGHT_BASES = {"g", "kg", "ounce", "pound"}
_WORD = re.compile(r"\w+")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Tandoor unit names, folded, to the key of the weight tables.
_UNIT_KEYS = {
    "stuck": "stuck",
    "pcs": "stuck",
    "piece": "stuck",
    "pieces": "stuck",
    "zehe": "zehe",
    "zehen": "zehe",
    "clove": "zehe",
    "cloves": "zehe",
    "el": "el",
    "essloffel": "el",
    "tbsp": "el",
    "tablespoon": "el",
    "tablespoons": "el",
    "tl": "tl",
    "teeloffel": "tl",
    "tsp": "tl",
    "teaspoon": "tl",
    "teaspoons": "tl",
    "prise": "prise",
    "prisen": "prise",
    "pinch": "prise",
    "bund": "bund",
    "handvoll": "handvoll",
    "stange": "stange",
    "stangen": "stange",
    "dose": "dose",
    "dosen": "dose",
    "can": "dose",
    "cm": "cm",
    "ml": "ml",
    "l": "l",
    "liter": "l",
}

# Grams in one unit, by a word of the food's name. Common German sizes: a
# medium onion, a level spoon of the food in question. They are suggestions
# for the review, not measurements.
_BY_FOOD: dict[str, dict[str, float]] = {
    "stuck": {
        "zwiebel": 110,
        "fruhlingszwiebel": 15,
        "schalotte": 30,
        "knoblauchzehe": 4,
        "karotte": 60,
        "mohre": 60,
        "limette": 65,
        "zitrone": 65,
        "orange": 150,
        "aubergine": 300,
        "tomate": 120,
        "kirschtomate": 17,
        "paprika": 160,
        "spitzpaprika": 50,
        "chili": 15,
        "zucchini": 200,
        "kartoffel": 150,
        "susskartoffel": 250,
        "banane": 115,
        "apfel": 180,
        "ei": 50,
        "avocado": 150,
        "gurke": 400,
        "champignon": 20,
        "lasagneplatte": 20,
        "lorbeerblatt": 0.2,
        "tortilla": 60,
    },
    "zehe": {"knoblauch": 4},
    "cm": {"ingwer": 5},
    "bund": {
        "petersilie": 40,
        "koriander": 30,
        "schnittlauch": 25,
        "dill": 25,
        "basilikum": 30,
        "fruhlingszwiebel": 120,
        "radieschen": 150,
    },
    "handvoll": {
        "basilikum": 10,
        "petersilie": 10,
        "koriander": 10,
        "minze": 10,
        "spinat": 30,
        "rucola": 20,
        "beere": 60,
        "heidelbeere": 60,
        "nuss": 30,
    },
    "stange": {"sellerie": 40, "lauch": 200, "porree": 200, "zimt": 3, "rhabarber": 100},
    "dose": {
        "tomate": 400,
        "kokosmilch": 400,
        "bohne": 240,
        "kichererbse": 240,
        "linse": 240,
        "mais": 140,
    },
    "el": {
        "ol": 13,
        "olivenol": 13,
        "rapsol": 13,
        "sonnenblumenol": 13,
        "sesamol": 13,
        "kokosol": 13,
        "pflanzenol": 13,
        "speiseol": 13,
        "erdnussmus": 16,
        "nussmus": 16,
        "mandelmus": 16,
        "tomatenmark": 16,
        "sojasauce": 16,
        "sojasoße": 16,
        "sirup": 20,
        "honig": 21,
        "mehl": 8,
        "starke": 9,
        "sesam": 9,
        "hefeflocken": 5,
        "senf": 15,
        "zucker": 12,
        "essig": 15,
        "mus": 16,
        "tahini": 15,
        "semmelbrosel": 7,
        "miso": 17,
        "misopaste": 17,
        "chiasamen": 12,
        "joghurt": 15,
        "currypaste": 15,
        "margarine": 14,
        "butter": 14,
        "wasser": 15,
        "zitronensaft": 15,
        "kakao": 6,
        "kakaopulver": 6,
        "erdnusse": 9,
        "kokosmilch": 15,
    },
    "tl": {
        "salz": 6,
        "kreuzkummel": 2.1,
        "kurkuma": 3,
        "oregano": 1,
        "thymian": 1,
        "majoran": 0.6,
        "basilikum": 0.7,
        "paprikapulver": 2.3,
        "paprika": 2.3,
        "zimt": 2.6,
        "chiliflocken": 1.8,
        "chili": 1.8,
        "pfeffer": 2.3,
        "koriander": 1.8,
        "kummel": 2.1,
        "masala": 2,
        "senf": 5,
        "zitronensaft": 5,
        "sojasauce": 5,
        "sirup": 7,
        "backpulver": 4.6,
        "natron": 4.6,
        "starke": 3,
        "kakao": 2,
        "kakaopulver": 2,
        "vanilleextrakt": 4.2,
        "sriracha": 6.5,
        "miso": 6,
        "misopaste": 6,
        "ol": 4.5,
        "olivenol": 4.5,
        "rapsol": 4.5,
        "sesamol": 4.5,
        "currypaste": 5,
        "zucker": 4,
        "essig": 5,
        "wasser": 5,
    },
}

# Grams per ml for liquids that are clearly not water-like.
_DENSITY = {
    "ol": 0.91,
    "olivenol": 0.91,
    "rapsol": 0.91,
    "sonnenblumenol": 0.91,
    "kokosmilch": 0.97,
    "milch": 1.03,
    "honig": 1.4,
    "sirup": 1.32,
}

# A generic guess per unit when the food is not in the table.
_GENERIC = {"zehe": 4, "bund": 30, "dose": 400, "prise": 0.4, "el": 10, "tl": 3}


def _fits(word: str, key: str) -> bool:
    """`key` names the word itself, its plural, or the head of a compound:
    "zwiebeln" and "speisezwiebel" fit "zwiebel"; "weizen" does not fit "ei"."""
    for suffix in ("", "n", "en", "e", "s", "er", "nen"):
        if word == key + suffix or (len(key) >= 4 and word.endswith(key + suffix)):
            return True
    return False


def suggest_grams(food_name: str, unit_name: str) -> tuple[float | None, str]:
    """Grams in one `unit_name` of the food, and whether that came from the
    food table ("food"), a generic guess ("unit") or nothing ("")."""
    key = _UNIT_KEYS.get(_fold(unit_name).strip())
    words = _WORD.findall(_fold(food_name))
    if key in ("ml", "l"):
        per_ml = _lookup(_DENSITY, words)
        factor = 1000 if key == "l" else 1
        if per_ml is not None:
            return round(per_ml * factor, 3), "food"
        return float(factor), "unit"
    if key is None:
        return None, ""
    grams = _lookup(_BY_FOOD.get(key, {}), words)
    if grams is not None:
        return grams, "food"
    generic = _GENERIC.get(key)
    return (float(generic), "unit") if generic is not None else (None, "")


def _lookup(table: dict[str, float], words: list[str]) -> float | None:
    # The longest key wins, so "spitzpaprika" beats "paprika".
    for key in sorted(table, key=len, reverse=True):
        if any(_fits(w, key) for w in words):
            return float(table[key])
    return None


def _is_weight(unit: dict[str, Any] | None) -> bool:
    if not unit:
        return False
    return (unit.get("base_unit") or "") in _WEIGHT_BASES or _fold(unit.get("name") or "") in (
        "g",
        "kg",
        "gramm",
    )


def _covered(conversions: list[dict[str, Any]], food_id: int, unit_id: int) -> float | None:
    """Grams per unit from an existing conversion for this food (or for every
    food) between this unit and a weight unit, or None."""
    for c in conversions:
        food = c.get("food")
        if food is not None and food.get("id") != food_id:
            continue
        base, conv = c.get("base_unit") or {}, c.get("converted_unit") or {}
        try:
            base_amount, conv_amount = float(c["base_amount"]), float(c["converted_amount"])
        except KeyError, TypeError, ValueError:
            continue
        if base_amount <= 0 or conv_amount <= 0:
            continue
        # Only grams count here; a conversion to kg would need scaling this table does not need.
        if base.get("id") == unit_id and _fold(conv.get("name") or "") == "g":
            return conv_amount / base_amount
        if conv.get("id") == unit_id and _fold(base.get("name") or "") == "g":
            return base_amount / conv_amount
    return None


@dataclass
class _Gap:
    food: dict[str, Any]
    unit: str
    recipes: set[int] = field(default_factory=set)
    ingredient_ids: list[int] = field(default_factory=list)
    existing: float | None = None


def find_gaps(
    recipes: list[dict[str, Any]], conversions: list[dict[str, Any]], piece_id: int | None = None
) -> list[_Gap]:
    """Food and unit pairs Tandoor cannot turn into grams, across `recipes`.
    `piece_id` is Tandoor's Stück unit, if it has one."""
    gaps: dict[tuple[int, str], _Gap] = {}
    for recipe in recipes:
        for step in recipe.get("steps") or []:
            for ing in step.get("ingredients") or []:
                food, unit = ing.get("food"), ing.get("unit")
                amount = float(ing.get("amount") or 0)
                if not food or ing.get("is_header") or ing.get("no_amount") or amount <= 0:
                    continue
                if unit is None:
                    gap = gaps.setdefault((food["id"], PIECE), _Gap(food, PIECE))
                    gap.ingredient_ids.append(ing["id"])
                    gap.recipes.add(recipe["id"])
                    continue
                if _is_weight(unit):
                    continue
                existing = _covered(conversions, food["id"], unit["id"])
                if existing is not None:
                    continue
                gap = gaps.setdefault((food["id"], unit["name"]), _Gap(food, unit["name"]))
                gap.recipes.add(recipe["id"])
    # A unit-less amount whose Stück conversion exists only needs its unit set.
    if piece_id is not None:
        for gap in gaps.values():
            if gap.ingredient_ids:
                gap.existing = _covered(conversions, gap.food["id"], piece_id)
    return sorted(gaps.values(), key=lambda g: (-len(g.recipes), _fold(g.food["name"]), g.unit))


def build_rows(gaps: list[_Gap]) -> list[dict[str, str]]:
    rows = []
    for g in gaps:
        if g.existing is not None:
            grams, basis = g.existing, "exists"
        else:
            grams, basis = suggest_grams(g.food["name"], g.unit)
        rows.append(
            {
                "food_id": str(g.food["id"]),
                "food_name": g.food["name"],
                "unit": g.unit,
                "grams": "" if grams is None else f"{grams:g}",
                "basis": basis,
                "recipes": str(len(g.recipes)),
                "ingredient_ids": " ".join(str(i) for i in g.ingredient_ids),
                "ok": "",
            }
        )
    return rows


def write_csv(rows: list[dict[str, str]], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def read_approved(path: Path) -> list[dict[str, str]]:
    """Rows marked `y`. A marked row without a positive weight stops the run
    before anything is written."""
    with path.open(newline="", encoding="utf-8") as f:
        approved = [r for r in csv.DictReader(f) if (r.get("ok") or "").strip().lower() == "y"]
    for r in approved:
        try:
            grams = float((r.get("grams") or "").replace(",", "."))
        except ValueError:
            grams = 0
        if grams <= 0:
            raise ValueError(f"{r['food_name']} / {r['unit']} is marked y but has no grams")
    return approved


async def apply_rows(client: TandoorClient, rows: list[dict[str, str]]) -> list[str]:
    lines = []
    units: dict[str, dict[str, Any]] = {}
    for r in rows:
        grams = float(r["grams"].replace(",", "."))
        unit = units.get(r["unit"]) or await client.ensure_unit(r["unit"])
        units[r["unit"]] = unit
        food = {"id": int(r["food_id"]), "name": r["food_name"]}
        if r.get("basis") != "exists":
            await client.add_unit_conversion(food, unit, grams)
        ids = [int(i) for i in (r.get("ingredient_ids") or "").split()]
        for ingredient_id in ids:
            await client.set_ingredient_unit(ingredient_id, unit)
        note = f", unit set on {len(ids)} ingredient(s)" if ids else ""
        lines.append(f"{r['food_name']}: 1 {unit['name']} = {grams:g} g{note}")
    return lines


def _client() -> TandoorClient:
    if not config.TANDOOR_URL or not config.TANDOOR_TOKEN:
        raise SystemExit("Set TANDOOR_URL and TANDOOR_TOKEN.")
    return TandoorClient(config.TANDOOR_URL, config.TANDOOR_TOKEN)


async def _suggest(out: Path) -> None:
    client = _client()
    try:
        recipes = [await client.recipe(i) for i in await client.recipe_ids()]
        conversions = await client.unit_conversions()
        units = await client.units()
    finally:
        await client.aclose()
    piece = next((u["id"] for u in units if _fold(u.get("name") or "") == _fold(PIECE)), None)
    rows = build_rows(find_gaps(recipes, conversions, piece))
    write_csv(rows, out)
    blank = sum(1 for r in rows if not r["grams"])
    print(f"{len(rows)} food/unit pairs without a gram conversion -> {out} ({blank} without a suggestion)")


async def _apply(csv_path: Path) -> None:
    rows = read_approved(csv_path)
    if not rows:
        print("No rows marked y. Nothing written.")
        return
    client = _client()
    try:
        for line in await apply_rows(client, rows):
            print(line)
    finally:
        await client.aclose()
    print(f"Wrote {len(rows)} conversions.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m snacky.sources.tandoor_units")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("suggest", help="write gram conversions the recipes are missing")
    s.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("apply", help="write rows marked y to Tandoor")
    a.add_argument("csv", type=Path)
    args = p.parse_args(argv)
    try:
        if args.cmd == "suggest":
            asyncio.run(_suggest(args.out))
        else:
            asyncio.run(_apply(args.csv))
    except (TandoorError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
