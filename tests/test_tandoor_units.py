"""tandoor_units tests. Recipes follow the 2.6.15 RecipeSerializer shape, cut
down to the fields the module reads; the foods are made up."""

import json

import httpx
import pytest
import respx

from snacky.sources import tandoor_units as tu
from snacky.sources.tandoor import TandoorClient

BASE = "http://tandoor.invalid"
G = {"id": 1, "name": "g", "plural_name": "g", "base_unit": "g"}
KG = {"id": 2, "name": "kg", "plural_name": "kg", "base_unit": "kg"}
EL = {"id": 3, "name": "EL", "plural_name": "EL", "base_unit": "tbsp"}
PIECE = {"id": 4, "name": "Stück", "plural_name": "Stück", "base_unit": None}
DOSE = {"id": 5, "name": "Dose", "plural_name": "Dosen", "base_unit": None}
ML = {"id": 6, "name": "ml", "plural_name": "ml", "base_unit": "ml"}


def ing(iid, food_id, name, amount, unit, **extra):
    return {"id": iid, "food": {"id": food_id, "name": name}, "unit": unit, "amount": amount, **extra}


RECIPES = [
    {
        "id": 1,
        "steps": [
            {
                "ingredients": [
                    ing(11, 101, "Test Zwiebel", 1, None),
                    ing(12, 102, "Test Olivenöl", 2, EL),
                    ing(13, 103, "Test Linsen", 200, G),
                    ing(14, 104, "Test Salz", 0, None),
                    ing(15, 105, "Test Gewürz", 1, EL, no_amount=True),
                    {"id": 16, "food": None, "unit": None, "amount": 0, "is_header": True},
                    ing(17, 106, "Test Kokosmilch", 200, ML),
                ]
            }
        ],
    },
    {
        "id": 2,
        "steps": [
            {
                "ingredients": [
                    ing(21, 101, "Test Zwiebel", 2, None),
                    ing(22, 102, "Test Olivenöl", 1, EL),
                    ing(23, 107, "Test Bohnen", 1, DOSE),
                    ing(24, 108, "Test Mehl", 0.5, KG),
                    ing(25, 109, "Test Ding", 1, PIECE),
                ]
            }
        ],
    },
]

# Test Bohnen already has a Dose conversion, written the other way round.
CONVERSIONS = [
    {
        "id": 1,
        "base_amount": 240,
        "base_unit": G,
        "converted_amount": 1,
        "converted_unit": DOSE,
        "food": {"id": 107, "name": "Test Bohnen"},
    }
]


def test_find_gaps_lists_what_tandoor_cannot_convert():
    gaps = tu.find_gaps(RECIPES, CONVERSIONS)
    got = {(g.food["name"], g.unit): (sorted(g.recipes), g.ingredient_ids) for g in gaps}
    assert got == {
        ("Test Zwiebel", "Stück"): ([1, 2], [11, 21]),
        ("Test Olivenöl", "EL"): ([1, 2], []),
        ("Test Kokosmilch", "ml"): ([1], []),
        ("Test Ding", "Stück"): ([2], []),
    }
    # Most-used first, so the review starts with what unblocks most recipes.
    assert [g.food["name"] for g in gaps][:2] == ["Test Olivenöl", "Test Zwiebel"]


def test_unit_less_amount_with_existing_piece_conversion_only_needs_its_unit():
    piece = [
        {
            **CONVERSIONS[0],
            "base_amount": 1,
            "base_unit": PIECE,
            "converted_amount": 110,
            "converted_unit": G,
            "food": {"id": 101, "name": "Test Zwiebel"},
        }
    ]
    rows = tu.build_rows(tu.find_gaps(RECIPES, piece, piece_id=PIECE["id"]))
    onion = next(r for r in rows if r["food_name"] == "Test Zwiebel")
    assert (onion["grams"], onion["basis"], onion["ingredient_ids"]) == ("110", "exists", "11 21")


@pytest.mark.parametrize(
    ("food", "unit", "expected"),
    [
        ("Zwiebel", "Stück", (110, "food")),
        ("rote Zwiebeln", None, (110, "food")),
        ("Frühlingszwiebel", "Stück", (15, "food")),
        ("Knoblauchzehe", "Stück", (4, "food")),
        ("Knoblauch", "Zehen", (4, "food")),
        ("Olivenöl", "EL", (13, "food")),
        ("Kreuzkümmel gemahlen", "TL", (2.1, "food")),
        ("Paprikapulver edelsüß", "TL", (2.3, "food")),
        ("Spitzpaprika", "Stück", (50, "food")),
        ("Weizenmehl", "EL", (8, "food")),
        ("Kokosmilch", "ml", (0.97, "food")),
        ("Hafermilch", "l", (1030, "food")),
        ("Gemüsebrühe", "ml", (1, "unit")),
        ("Ingwer", "cm", (5, "food")),
        ("Unbekanntes", "EL", (10, "unit")),
        ("Weizen", "Stück", (None, "")),
        ("Unbekanntes", "Packung", (None, "")),
    ],
)
def test_suggest_grams(food, unit, expected):
    assert tu.suggest_grams(food, unit or "Stück") == expected


def test_review_refuses_marked_rows_without_grams(tmp_path):
    rows = tu.build_rows(tu.find_gaps(RECIPES, CONVERSIONS))
    for r in rows:
        r["ok"] = "y"
    path = tmp_path / "u.csv"
    tu.write_csv(rows, path)
    with pytest.raises(ValueError, match="Test Ding"):
        tu.read_approved(path)


@respx.mock
async def test_apply_adds_conversions_and_sets_missing_units(tmp_path):
    rows = tu.build_rows(tu.find_gaps(RECIPES, CONVERSIONS))
    for r in rows:
        if r["food_name"] in ("Test Zwiebel", "Test Olivenöl"):
            r["ok"] = "y"
    path = tmp_path / "u.csv"
    tu.write_csv(rows, path)

    page = {"count": 3, "next": None, "previous": None, "results": [G, EL, PIECE]}
    respx.get(f"{BASE}/api/unit/").respond(json=page)
    created = respx.post(f"{BASE}/api/unit-conversion/").respond(json={"id": 9})
    patched = respx.patch(url__regex=rf"{BASE}/api/ingredient/\d+/").respond(json={})

    client = TandoorClient(BASE, "t", httpx.AsyncClient())
    lines = await tu.apply_rows(client, tu.read_approved(path))

    assert created.call_count == 2
    bodies = {
        json.loads(c.request.content)["food"]["name"]: json.loads(c.request.content) for c in created.calls
    }
    onion = bodies["Test Zwiebel"]
    assert onion["food"] == {"id": 101, "name": "Test Zwiebel"}
    assert (onion["base_amount"], onion["base_unit"]["id"]) == (1, PIECE["id"])
    assert (onion["converted_amount"], onion["converted_unit"]["name"]) == (110, "g")
    assert bodies["Test Olivenöl"]["converted_amount"] == 13
    assert sorted(str(c.request.url) for c in patched.calls) == [
        f"{BASE}/api/ingredient/11/",
        f"{BASE}/api/ingredient/21/",
    ]
    assert json.loads(patched.calls.last.request.content) == {"unit": PIECE}
    assert any("unit set on 2 ingredient(s)" in line for line in lines)


def test_apply_with_nothing_approved_writes_nothing(tmp_path, capsys, monkeypatch):
    path = tmp_path / "u.csv"
    tu.write_csv(tu.build_rows(tu.find_gaps(RECIPES, CONVERSIONS)), path)
    monkeypatch.setattr(tu.config, "TANDOOR_URL", "")
    assert tu.main(["apply", str(path)]) == 0
    assert "Nothing written" in capsys.readouterr().out
