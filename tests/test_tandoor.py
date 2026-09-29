"""Tandoor client tests. Fixtures under tests/fixtures/tandoor follow the
2.6.15 serializers; nothing here touches the network."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from snacky.model import Nutrients
from snacky.sources.tandoor import TandoorClient, TandoorError

FIX = Path(__file__).parent / "fixtures" / "tandoor"
BASE = "http://tandoor.invalid"


def fx(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
async def client():
    c = TandoorClient(BASE, "secret-token")
    yield c
    await c.aclose()


def mock_types(router, name="property_types.json"):
    return router.get(f"{BASE}/api/property-type/").respond(json=fx(name))


@respx.mock
async def test_complete_recipe_is_divided_by_servings(client):
    mock_types(respx)
    route = respx.get(f"{BASE}/api/recipe/7/").respond(json=fx("recipe_complete.json"))
    r = await client.recipe_nutrition(7)
    assert r.name == "Test Oat Bowl"
    assert r.servings == 2
    assert r.complete and r.missing == ()
    assert r.per_serving == Nutrients(400, 21, 10, 60, 10)
    assert route.calls.last.request.headers["authorization"] == "Bearer secret-token"


@respx.mock
async def test_missing_conversion_and_missing_unit_are_named(client):
    mock_types(respx)
    respx.get(f"{BASE}/api/recipe/8/").respond(json=fx("recipe_missing.json"))
    r = await client.recipe_nutrition(8)
    assert not r.complete
    assert r.missing == ("Mystery Spice Mix", "Test Egg")
    assert r.per_serving.kcal == 140  # 560 / 4 servings


@respx.mock
async def test_fibre_gap_blanks_fibre_but_stays_complete(client):
    mock_types(respx)
    respx.get(f"{BASE}/api/recipe/9/").respond(json=fx("recipe_fibre_gap.json"))
    r = await client.recipe_nutrition(9)
    assert r.complete
    assert r.per_serving.fibre_g is None
    assert r.per_serving.protein_g == 21


@respx.mock
async def test_names_map_when_there_is_no_fdc_id(client):
    mock_types(respx, "property_types_names_only.json")
    respx.get(f"{BASE}/api/recipe/10/").respond(json=fx("recipe_names_only.json"))
    r = await client.recipe_nutrition(10)
    assert r.per_serving == Nutrients(300, 15, 9, 40, 5)


@respx.mock
async def test_fdc_id_beats_name(client):
    mock_types(respx, "property_types_fdc_wins.json")
    respx.get(f"{BASE}/api/recipe/7/").respond(json={**fx("recipe_complete.json"), "food_properties": {}})
    # Protein is the type named "Notes" (fdc 1003), not the one named "Eiweiß".
    from snacky.sources.tandoor import map_types

    types = await client.property_types()
    mapped = map_types(types)
    assert mapped["protein_g"].name == "Notes"
    assert mapped["carbs_g"].name == "Kohlenhydrate"
    assert "fibre_g" not in mapped


@respx.mock
async def test_kilojoule_energy_is_converted(client):
    mock_types(respx, "property_types_kj.json")
    recipe = fx("recipe_complete.json")
    fp = {}
    for i, total in zip((41, 42, 43, 44), (4184, 20, 10, 60), strict=True):
        fp[str(i)] = {"total_value": total, "missing_value": False, "food_values": {}}
    recipe["food_properties"] = fp
    recipe["servings"] = 1
    respx.get(f"{BASE}/api/recipe/7/").respond(json=recipe)
    r = await client.recipe_nutrition(7)
    assert r.per_serving.kcal == pytest.approx(1000)


@respx.mock
async def test_missing_required_type_raises(client):
    mock_types(respx, "property_types_partial.json")
    respx.get(f"{BASE}/api/recipe/7/").respond(json=fx("recipe_complete.json"))
    with pytest.raises(TandoorError, match="fat_g"):
        await client.recipe_nutrition(7)


@respx.mock
async def test_http_errors_become_tandoor_errors(client):
    respx.get(f"{BASE}/api/property-type/").respond(401, json={"detail": "bad token"})
    with pytest.raises(TandoorError, match="401"):
        await client.property_types()


@respx.mock
async def test_unreachable_server_becomes_tandoor_error(client):
    respx.get(f"{BASE}/api/property-type/").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TandoorError, match="unreachable"):
        await client.property_types()


@respx.mock
async def test_list_foods_follows_all_pages(client):
    route = respx.get(f"{BASE}/api/food/").mock(
        side_effect=lambda req: httpx.Response(
            200, json=fx("foods_page1.json" if req.url.params["page"] == "1" else "foods_page2.json")
        )
    )
    foods = await client.list_foods()
    assert [f.id for f in foods] == [101, 102, 103]
    assert foods[0].properties == {11: 370, 12: 13.5, 13: 7, 14: 59, 15: 10}
    assert foods[2].properties_food_unit is None
    assert route.call_count == 2


@respx.mock
async def test_ensure_creates_only_missing_types(client):
    mock_types(respx, "property_types_partial.json")
    created = []

    def create(req):
        body = json.loads(req.content)
        created.append(body)
        return httpx.Response(201, json={**body, "id": 50 + len(created), "description": None, "order": 0})

    respx.post(f"{BASE}/api/property-type/").mock(side_effect=create)
    types = await client.ensure_property_types()
    assert [c["fdc_id"] for c in created] == [1004, 1005, 1079]
    assert created[0] == {"name": "Fett", "unit": "g", "fdc_id": 1004}
    assert set(types) == {"kcal", "protein_g", "fat_g", "carbs_g", "fibre_g"}
    assert types["kcal"].id == 11


@respx.mock
async def test_ensure_creates_nothing_when_all_exist(client):
    mock_types(respx)
    post = respx.post(f"{BASE}/api/property-type/")
    await client.ensure_property_types()
    assert not post.called


@respx.mock
async def test_set_food_properties_updates_existing_and_keeps_others(client):
    mock_types(respx)
    respx.get(f"{BASE}/api/unit/").respond(json=fx("units.json"))
    respx.get(f"{BASE}/api/food/102/").respond(json=fx("food_partial.json"))
    patch = respx.patch(f"{BASE}/api/food/102/").respond(json=fx("foods_page1.json")["results"][1])
    await client.set_food_properties(102, Nutrients(64, 3.4, 3.6, 4.8, None))
    body = json.loads(patch.calls.last.request.content)
    assert body["properties_food_amount"] == 100
    assert body["properties_food_unit"]["name"] == "g"
    props = body["properties"]
    by_type = {p["property_type"]["id"]: p for p in props}
    # Kalorien keeps its property id, so Tandoor updates it instead of adding a second one.
    assert by_type[11]["id"] == 6 and by_type[11]["property_amount"] == 64
    assert "id" not in by_type[12] and by_type[12]["property_amount"] == 3.4
    assert by_type[12]["property_type"]["fdc_id"] == 1003
    assert by_type[99]["property_amount"] == 5.0  # unrelated property survives
    assert 15 not in by_type  # no fibre value, nothing written
    assert len(props) == len(by_type)


@respx.mock
async def test_set_food_properties_creates_gram_unit_when_missing(client):
    mock_types(respx)
    respx.get(f"{BASE}/api/unit/").respond(json=fx("units_no_gram.json"))
    unit = respx.post(f"{BASE}/api/unit/").respond(
        201,
        json={
            "id": 9,
            "name": "g",
            "plural_name": "g",
            "description": None,
            "base_unit": "g",
            "open_data_slug": None,
        },
    )
    respx.get(f"{BASE}/api/food/103/").respond(json=fx("foods_page2.json")["results"][0])
    patch = respx.patch(f"{BASE}/api/food/103/").respond(json=fx("foods_page2.json")["results"][0])
    await client.set_food_properties(103, Nutrients(350, 25, 1.5, 55, 12))
    assert json.loads(unit.calls.last.request.content)["base_unit"] == "g"
    body = json.loads(patch.calls.last.request.content)
    assert body["properties_food_unit"]["id"] == 9
    assert sorted(p["property_type"]["id"] for p in body["properties"]) == [11, 12, 13, 14, 15]


@respx.mock
async def test_repeated_food_with_an_unconvertible_unit_is_incomplete(client):
    # Tandoor keeps the first amount's value and only adds the flag when the same
    # food comes up again in a unit it cannot convert.
    mock_types(respx)
    recipe = fx("recipe_complete.json")
    entry = recipe["food_properties"]["12"]
    entry["missing_value"] = True
    entry["food_values"]["102"]["missing_conversion"] = {
        "base_unit": {"id": 3, "name": "cup"},
        "converted_unit": {"id": 1, "name": "g"},
    }
    respx.get(f"{BASE}/api/recipe/7/").respond(json=recipe)
    r = await client.recipe_nutrition(7)
    assert not r.complete
    assert r.missing == ("Test Milk",)


@respx.mock
async def test_new_property_keeps_the_type_order(client):
    # Tandoor saves a new property with a non-partial serializer, which resets the
    # nested type's order to 0 unless the order is in the payload.
    mock_types(respx)
    respx.get(f"{BASE}/api/unit/").respond(json=fx("units.json"))
    respx.get(f"{BASE}/api/food/102/").respond(json=fx("food_partial.json"))
    patch = respx.patch(f"{BASE}/api/food/102/").respond(json=fx("foods_page1.json")["results"][1])
    await client.set_food_properties(102, Nutrients(64, 3.4, 3.6, 4.8, None))
    body = json.loads(patch.calls.last.request.content)
    protein = next(p for p in body["properties"] if p["property_type"]["id"] == 12)
    assert protein["property_type"]["order"] == 12


@respx.mock
async def test_energy_is_written_in_the_unit_of_its_type(client):
    types = fx("property_types_kj.json")
    types["results"].append({"id": 45, "name": "Ballaststoffe", "unit": "g", "fdc_id": 1079, "order": 45})
    respx.get(f"{BASE}/api/property-type/").respond(json=types)
    respx.get(f"{BASE}/api/unit/").respond(json=fx("units.json"))
    respx.get(f"{BASE}/api/food/103/").respond(json=fx("foods_page2.json")["results"][0])
    patch = respx.patch(f"{BASE}/api/food/103/").respond(json=fx("foods_page2.json")["results"][0])
    await client.set_food_properties(103, Nutrients(100, 25, 1.5, 55, 12))
    body = json.loads(patch.calls.last.request.content)
    energy = next(p for p in body["properties"] if p["property_type"]["id"] == 41)
    assert energy["property_amount"] == pytest.approx(418.4)
