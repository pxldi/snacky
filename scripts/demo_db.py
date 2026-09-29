"""Create a database with two weeks of made-up entries, goals and quick items.

    uv run python scripts/demo_db.py /tmp/snacky-demo.sqlite
    uv run python scripts/serve_web.py /tmp/snacky-demo.sqlite

Everything here is invented. The foods are generic and the numbers are round.
"""

from __future__ import annotations

import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from snacky import config
from snacky.model import (
    Confidence,
    FoodCandidate,
    Goal,
    GoalKind,
    Nutrients,
    Origin,
    Serving,
    Source,
)
from snacky.store import Store

# name, source, kcal, protein, fat, carbs, fibre per 100 g, servings
_FOODS = [
    ("Sojajoghurt natur", Source.OFF, 50, 4, 2.3, 2.5, 0.6, (Serving("1 Becher", 400),)),
    ("Haferflocken", Source.BLS, 372, 13.5, 7, 59, 10, (Serving("1 Portion", 60),)),
    ("Seitan", Source.MANUAL, 130, 25, 2, 4, 0.5, ()),
    ("Kichererbsen, gekocht", Source.BLS, 140, 8.5, 2.6, 20, 6, ()),
    ("Banane", Source.BLS, 90, 1.1, 0.2, 20, 2, (Serving("1 Stück", 120),)),
    ("Reis, gekocht", Source.BLS, 130, 2.7, 0.3, 28, 0.4, ()),
    ("Erbsenprotein-Pulver", Source.LABEL, 380, 78, 5, 8, 2, (Serving("1 Scoop", 30),)),
    ("Vollkornbrot", Source.BLS, 210, 7, 1.5, 40, 7, (Serving("1 Scheibe", 50),)),
    ("Tofu natur", Source.OFF, 125, 12, 7, 1, 1, (Serving("1 Block", 200),)),
    ("Linsen, gekocht", Source.BLS, 115, 9, 0.4, 20, 8, ()),
    ("Erdnussmus", Source.LABEL, 600, 25, 50, 12, 6, (Serving("1 EL", 15),)),
    ("Apfel", Source.BLS, 55, 0.3, 0.4, 12, 2, (Serving("1 Stück", 180),)),
]

_QUICK = [
    ("Proteinshake (Erbse)", "Erbsenprotein-Pulver", 30),
    ("Sojajoghurt", "Sojajoghurt natur", 250),
    ("Banane", "Banane", 120),
]

# (hour, minute, [(food, grams)]) per meal; each day picks a variation of these.
_DAY_PLAN = [
    (7, 40, [("Haferflocken", 60), ("Sojajoghurt natur", 200), ("Banane", 120)]),
    (12, 45, [("Seitan", 150), ("Reis, gekocht", 200)]),
    (12, 45, [("Linsen, gekocht", 250), ("Vollkornbrot", 100)]),
    (16, 0, [("Erdnussmus", 30), ("Apfel", 180)]),
    (19, 30, [("Tofu natur", 200), ("Reis, gekocht", 180)]),
    (19, 30, [("Kichererbsen, gekocht", 250), ("Vollkornbrot", 100)]),
]


def build(out: str | Path, today: date | None = None) -> Store:
    rng = random.Random(7)
    store = Store(out)
    today = today or datetime.now(config.TZ).date()
    foods = {}
    for i, (name, source, kcal, protein, fat, carbs, fibre, servings) in enumerate(_FOODS):
        foods[name] = store.upsert_food(
            FoodCandidate(
                name=name,
                source=source,
                per_100g=Nutrients(kcal, protein, fat, carbs, fibre),
                source_ref=f"demo-{i}",
                servings=servings,
            )
        )
    store.set_goal(Goal("protein_g", GoalKind.MIN, today - timedelta(days=60), min=120))
    store.set_goal(Goal("kcal", GoalKind.BAND, today - timedelta(days=60), min=2200, max=2600))
    for label, food, grams in _QUICK:
        store.add_quick_item(foods[food].id, grams, label)

    for back in range(14, -1, -1):
        day = today - timedelta(days=back)
        if back and rng.random() < 0.1:  # a day nothing was logged
            continue
        breakfast, lunch, snack, dinner = (
            _DAY_PLAN[0],
            rng.choice(_DAY_PLAN[1:3]),
            _DAY_PLAN[3],
            rng.choice(_DAY_PLAN[4:6]),
        )
        plan = [breakfast, lunch, dinner] + ([snack] if rng.random() < 0.7 else [])
        for hour, minute, items in plan:
            when = datetime.combine(day, time(hour, minute), tzinfo=config.TZ)
            if back == 0 and when > datetime.now(config.TZ):
                continue
            for offset, (name, grams) in enumerate(items):
                food = foods[name]
                grams = round(grams * rng.uniform(0.85, 1.15) / 5) * 5
                store.log_entry(
                    name=food.name,
                    nutrients=food.per_100g.for_grams(grams),
                    eaten_at=when + timedelta(minutes=3 * offset),
                    source=food.source,
                    origin=Origin.CHAT,
                    grams=grams,
                    food_id=food.id,
                )
        if rng.random() < 0.35:
            store.log_entry(
                name="Restaurant, Pasta mit Tomatensauce",
                nutrients=Nutrients(720, 24, 22, 100, None),
                eaten_at=datetime.combine(day, time(21, 15), tzinfo=config.TZ),
                source=Source.AI_ESTIMATE,
                origin=Origin.CHAT,
                servings=1,
                confidence=rng.choice([Confidence.MEDIUM, Confidence.LOW]),
                assumptions="Eine Restaurantportion, etwa 350 g gekocht.",
            )
    return store


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: demo_db.py OUT")
    out = Path(sys.argv[1])
    if out.exists():
        raise SystemExit(f"{out} exists; remove it first")
    build(out).close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
