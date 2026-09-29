"""Fill Tandoor food properties from BLS, with a human in the loop.

    python -m snacky.sources.tandoor_match match --bls bls.sqlite --out matches.csv
    python -m snacky.sources.tandoor_match apply matches.csv

`match` writes one row per Tandoor food and BLS candidate. The reviewer puts
`y` in the `ok` column of the right candidate and leaves the rest empty.
`apply` writes only those rows. The nutrient values travel in the CSV, so
`apply` needs no BLS file and writes exactly what the reviewer saw.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from snacky import config
from snacky.model import FoodCandidate, Nutrients
from snacky.sources.tandoor import TandoorClient, TandoorError, TandoorFood

COLUMNS = [
    "food_id",
    "food_name",
    "bls_code",
    "bls_name",
    "kcal",
    "protein_g",
    "fat_g",
    "carbs_g",
    "fibre_g",
    "ok",
]


class Index(Protocol):
    def search(self, query: str, limit: int = 10) -> list[FoodCandidate]: ...


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:g}"


def build_rows(
    foods: Iterable[TandoorFood], index: Index, nutrient_type_ids: set[int], candidates: int = 3
) -> tuple[list[dict[str, str]], list[str]]:
    """Rows for foods that lack any of the five properties, plus the names of
    foods BLS had no candidate for."""
    rows: list[dict[str, str]] = []
    unmatched: list[str] = []
    for food in foods:
        if nutrient_type_ids <= food.properties.keys():
            continue
        found = index.search(food.name, limit=candidates)
        if not found:
            unmatched.append(food.name)
            continue
        for c in found:
            n = c.per_100g
            rows.append(
                {
                    "food_id": str(food.id),
                    "food_name": food.name,
                    "bls_code": c.source_ref or "",
                    "bls_name": c.name,
                    "kcal": _fmt(n.kcal),
                    "protein_g": _fmt(n.protein_g),
                    "fat_g": _fmt(n.fat_g),
                    "carbs_g": _fmt(n.carbs_g),
                    "fibre_g": _fmt(n.fibre_g),
                    "ok": "",
                }
            )
    return rows, unmatched


def write_csv(rows: list[dict[str, str]], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def read_approved(path: Path) -> list[dict[str, str]]:
    """Rows marked `y`. Two approved rows for one food are a mistake in the
    review, so that stops the whole run before anything is written."""
    with path.open(newline="", encoding="utf-8") as f:
        approved = [r for r in csv.DictReader(f) if (r.get("ok") or "").strip().lower() == "y"]
    seen: dict[str, str] = {}
    for r in approved:
        if r["food_id"] in seen:
            raise ValueError(f"food {r['food_id']} ({r['food_name']}) has more than one row marked y")
        seen[r["food_id"]] = r["bls_code"]
    return approved


def _nutrients(row: dict[str, str]) -> Nutrients:
    def num(key: str) -> float | None:
        v = (row.get(key) or "").strip()
        return float(v.replace(",", ".")) if v else None

    kcal, protein, fat, carbs = num("kcal"), num("protein_g"), num("fat_g"), num("carbs_g")
    if None in (kcal, protein, fat, carbs):
        raise ValueError(f"food {row['food_id']} ({row['food_name']}) is missing a required value")
    return Nutrients(kcal, protein, fat, carbs, num("fibre_g"))  # type: ignore[arg-type]


async def apply_rows(client: TandoorClient, rows: list[dict[str, str]]) -> list[str]:
    lines = []
    for r in rows:
        n = _nutrients(r)
        await client.set_food_properties(int(r["food_id"]), n)
        lines.append(
            f"{r['food_name']} <- BLS {r['bls_code']} {r['bls_name']}: "
            f"{n.kcal:g} kcal, {n.protein_g:g} g protein, {n.fat_g:g} g fat, "
            f"{n.carbs_g:g} g carbs, fibre {_fmt(n.fibre_g) or 'n/a'} per 100 g"
        )
    return lines


def _client() -> TandoorClient:
    if not config.TANDOOR_URL or not config.TANDOOR_TOKEN:
        raise SystemExit("Set TANDOOR_URL and TANDOOR_TOKEN.")
    return TandoorClient(config.TANDOOR_URL, config.TANDOOR_TOKEN)


async def _match(bls: Path, out: Path) -> None:
    from snacky.sources.bls import BlsIndex

    client = _client()
    try:
        types = await client.ensure_property_types()
        foods = await client.list_foods()
    finally:
        await client.aclose()
    ids = {t.id for t in types.values()}
    rows, unmatched = build_rows(foods, BlsIndex(bls), ids)
    write_csv(rows, out)
    print(f"{len({r['food_id'] for r in rows})} foods with candidates -> {out}")
    for name in unmatched:
        print(f"no BLS candidate: {name}", file=sys.stderr)


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
    print(f"Wrote {len(rows)} foods.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m snacky.sources.tandoor_match")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match", help="write BLS candidates for foods without nutrients")
    m.add_argument("--bls", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("apply", help="write rows marked y to Tandoor")
    a.add_argument("csv", type=Path)
    args = p.parse_args(argv)
    try:
        if args.cmd == "match":
            asyncio.run(_match(args.bls, args.out))
        else:
            asyncio.run(_apply(args.csv))
    except (TandoorError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
