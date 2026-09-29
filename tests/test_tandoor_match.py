import csv
import json
from pathlib import Path

import httpx
import respx

from snacky.model import FoodCandidate, Nutrients, Source
from snacky.sources import tandoor_match as tm
from snacky.sources.tandoor import TandoorClient, TandoorFood

FIX = Path(__file__).parent / "fixtures" / "tandoor"
BASE = "http://tandoor.invalid"


def cand(code, name, kcal=100.0, protein=5.0):
    return FoodCandidate(
        name=name, source=Source.BLS, per_100g=Nutrients(kcal, protein, 2.0, 10.0, None), source_ref=code
    )


class FakeIndex:
    def __init__(self, table):
        self.table = table
        self.queries = []

    def search(self, query, limit=10):
        self.queries.append(query)
        return self.table.get(query, [])[:limit]


FOODS = [
    TandoorFood(101, "Test Oats", {11: 1, 12: 1, 13: 1, 14: 1, 15: 1}),  # complete, skipped
    TandoorFood(102, "Test Milk", {11: 64}),
    TandoorFood(103, "Test Lentils"),
    TandoorFood(104, "Test Unknown"),
]
IDS = {11, 12, 13, 14, 15}
INDEX = FakeIndex(
    {
        "Test Milk": [cand("M100", "Milch 3,5%", 64, 3.4), cand("M200", "Milchreis")],
        "Test Lentils": [cand("H100", "Linsen, getrocknet", 330, 24)],
    }
)


def test_build_rows_skips_complete_foods_and_reports_unmatched():
    rows, unmatched = tm.build_rows(FOODS, INDEX, IDS)
    assert "Test Oats" not in INDEX.queries
    assert [(r["food_id"], r["bls_code"]) for r in rows] == [
        ("102", "M100"),
        ("102", "M200"),
        ("103", "H100"),
    ]
    assert unmatched == ["Test Unknown"]
    assert all(r["ok"] == "" for r in rows)
    assert rows[0]["protein_g"] == "3.4" and rows[0]["fibre_g"] == ""


def test_csv_round_trip_and_only_y_rows_are_read(tmp_path):
    rows, _ = tm.build_rows(FOODS, INDEX, IDS)
    rows[0]["ok"] = "Y"
    rows[2]["ok"] = "n"
    path = tmp_path / "m.csv"
    tm.write_csv(rows, path)
    assert next(csv.reader(path.open(encoding="utf-8"))) == tm.COLUMNS
    approved = tm.read_approved(path)
    assert [r["bls_code"] for r in approved] == ["M100"]


def test_two_approved_rows_for_one_food_are_refused(tmp_path):
    rows, _ = tm.build_rows(FOODS, INDEX, IDS)
    rows[0]["ok"] = rows[1]["ok"] = "y"
    path = tmp_path / "m.csv"
    tm.write_csv(rows, path)
    try:
        tm.read_approved(path)
    except ValueError as e:
        assert "more than one" in str(e)
    else:
        raise AssertionError("expected ValueError")


@respx.mock
async def test_apply_writes_only_approved_rows(tmp_path):
    rows, _ = tm.build_rows(FOODS, INDEX, IDS)
    rows[2]["ok"] = "y"  # lentils only
    path = tmp_path / "m.csv"
    tm.write_csv(rows, path)

    respx.get(f"{BASE}/api/property-type/").respond(
        json=json.loads((FIX / "property_types.json").read_text())
    )
    respx.get(f"{BASE}/api/unit/").respond(json=json.loads((FIX / "units.json").read_text()))
    lentils = json.loads((FIX / "foods_page2.json").read_text())["results"][0]
    respx.get(f"{BASE}/api/food/103/").respond(json=lentils)
    patch = respx.patch(f"{BASE}/api/food/103/").respond(json=lentils)
    other = respx.patch(f"{BASE}/api/food/102/").respond(json=lentils)

    client = TandoorClient(BASE, "t", httpx.AsyncClient())
    lines = await tm.apply_rows(client, tm.read_approved(path))
    assert patch.call_count == 1 and not other.called
    assert len(lines) == 1 and "Test Lentils" in lines[0] and "H100" in lines[0]
    body = json.loads(patch.calls.last.request.content)
    amounts = {p["property_type"]["id"]: p["property_amount"] for p in body["properties"]}
    assert amounts == {11: 330, 12: 24, 13: 2, 14: 10}


def test_apply_with_nothing_approved_writes_nothing(tmp_path, capsys, monkeypatch):
    rows, _ = tm.build_rows(FOODS, INDEX, IDS)
    path = tmp_path / "m.csv"
    tm.write_csv(rows, path)
    monkeypatch.setattr(tm.config, "TANDOOR_URL", "")
    assert tm.main(["apply", str(path)]) == 0
    assert "Nothing written" in capsys.readouterr().out
