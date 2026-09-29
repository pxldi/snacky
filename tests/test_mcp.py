"""Tool-level tests: every call goes through the MCP server. The store is in
memory, BLS is the fixture sample, and respx stands in for Open Food Facts,
Tandoor and openGym. Nothing touches the network."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from snacky import config
from snacky.lookup import Lookup
from snacky.mcp_server import create_mcp, create_mcp_app, parse_when
from snacky.model import FoodCandidate, Nutrients, Origin, Serving, Source
from snacky.sources import opengym as opengym_module
from snacky.sources.bls import BlsIndex, build
from snacky.sources.off import OffClient
from snacky.sources.opengym import OpenGymClient
from snacky.sources.tandoor import TandoorClient
from snacky.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)  # a Tuesday
OFF = "https://world.openfoodfacts.org"
SEARCH = "https://search.openfoodfacts.org"
TANDOOR = "http://tandoor.invalid"
GYM = "http://gym.invalid"


def fixture_json(*parts: str):
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def berlin(monkeypatch):
    monkeypatch.setattr(config, "TZ", BERLIN)
    monkeypatch.setattr(opengym_module, "TZ", BERLIN)


@pytest.fixture(scope="module")
def bls_file(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bls") / "bls.sqlite"
    build(FIXTURES / "bls" / "BLS_4_0_Daten_2025_DE_sample.xlsx", out)
    return out


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
async def clients(bls_file):
    bls = BlsIndex(bls_file)
    off = OffClient("snacky-test")
    tandoor = TandoorClient(TANDOOR, "t")
    gym = OpenGymClient(GYM, "g")
    yield bls, off, tandoor, gym
    bls.close()
    for c in (off, tandoor, gym):
        await c.aclose()


@pytest.fixture
def make(store, clients):
    """A server factory, so a test can pick the clock or leave services out."""
    bls, off, tandoor, gym = clients

    def build_server(now=NOW, *, with_tandoor=True, with_gym=True):
        return create_mcp(
            store,
            Lookup(store, bls, off),
            tandoor if with_tandoor else None,
            gym if with_gym else None,
            now=lambda: now,
        )

    return build_server


@pytest.fixture
def mcp(make):
    return make()


async def call(mcp, tool, /, **args) -> dict:
    result = await mcp.call_tool(tool, args)
    return json.loads(result.content[0].text)


async def fails(mcp, tool, match, /, **args) -> None:
    with pytest.raises(ToolError, match=match):
        await mcp.call_tool(tool, args)


def route_product(name="product_full.json", code="4000000000017"):
    return respx.get(f"{OFF}/api/v2/product/{code}.json").respond(json=fixture_json("off", name))


# --- tools list and health ---------------------------------------------------


async def test_all_tools_are_listed_with_argument_descriptions(mcp):
    tools = await mcp.list_tools()
    assert sorted(t.name for t in tools) == sorted(
        [
            "search_food",
            "log_food",
            "log_barcode",
            "log_label",
            "log_recipe_portion",
            "log_estimate",
            "day_summary",
            "week_summary",
            "update_entry",
            "delete_entry",
            "set_goal",
            "add_serving",
            "suggest_foods",
            "log_again",
            "recipe_nutrition",
        ]
    )
    for tool in tools:
        assert tool.description
        for arg, schema in tool.input_schema["properties"].items():
            assert schema.get("description") or "$ref" in schema or "items" in schema, (tool.name, arg)


def test_http_app_serves_health_and_tools_statelessly(mcp, monkeypatch):
    monkeypatch.setenv("IMAGE_SHA", "abc123")
    headers = {"Accept": "application/json, text/event-stream"}
    with TestClient(create_mcp_app(mcp)) as client:
        assert client.get("/health").json() == {"status": "ok", "server": "snacky", "build": "abc123"}
        listed = client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert "search_food" in [t["name"] for t in listed.json()["result"]["tools"]]
        called = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search_food", "arguments": {"query": "Tofu", "limit": 1}},
            },
        )
        text = called.json()["result"]["content"][0]["text"]
        assert json.loads(text)["matches"][0]["ref"] == "bls:H861000"


# --- search_food --------------------------------------------------------------


@respx.mock
async def test_search_food_names_ref_source_and_per_100g(mcp):
    out = await call(mcp, "search_food", query="Tofu", limit=2)
    first = out["matches"][0]
    assert first["ref"] == "bls:H861000"
    assert first["source"] == "bls"
    assert first["per_100g"] == {
        "kcal": 115.0,
        "protein_g": 15.5,
        "fat_g": 5.6,
        "carbs_g": 0.0,
        "fibre_g": 1.3,
    }
    assert len(out["matches"]) == 2 and out["notes"] == []


@respx.mock
async def test_search_food_survives_an_off_outage(mcp):
    respx.get(f"{SEARCH}/search").mock(side_effect=httpx.ConnectError("down"))
    out = await call(mcp, "search_food", query="Linse", limit=15)
    assert out["matches"] and all(m["source"] == "bls" for m in out["matches"])
    assert "Open Food Facts was skipped" in out["notes"][0]


# --- log_food / log_barcode ---------------------------------------------------


async def test_log_food_by_bls_ref_scales_the_database_values(mcp, store):
    out = await call(mcp, "log_food", food_ref="bls:H861000", grams=150)
    assert out["logged"] is True
    assert out["food"]["source"] == "bls"
    entry = out["entry"]
    assert entry["name"] == "Tofu" and entry["grams"] == 150
    assert entry["nutrients"]["kcal"] == 172.5
    assert entry["nutrients"]["protein_g"] == 23.3
    assert out["day_so_far"] == {"date": "2026-09-29", "kcal": 172.5, "protein_g": 23.3}
    stored = store.get_entry(entry["id"])
    assert stored.source is Source.BLS and stored.food_id is not None
    assert stored.eaten_at == NOW


async def test_log_food_by_stored_ref_and_by_serving(mcp):
    found = (await call(mcp, "search_food", query="Tofu", limit=1))["matches"][0]
    first = await call(mcp, "log_food", food_ref=found["ref"], grams=100)
    stored_ref = first["food"]["ref"]
    assert stored_ref.startswith("food:")
    await call(mcp, "add_serving", food_ref=stored_ref, label="1 Block", grams=200)
    out = await call(mcp, "log_food", food_ref=stored_ref, serving="1 block")
    assert out["serving"] == "1 Block"
    assert out["entry"]["grams"] == 200
    assert out["entry"]["nutrients"]["protein_g"] == 31.0


async def test_log_food_needs_exactly_one_amount(mcp):
    await fails(mcp, "log_food", "exactly one", food_ref="bls:H861000")
    await fails(mcp, "log_food", "exactly one", food_ref="bls:H861000", grams=10, serving="1 Block")
    await fails(mcp, "log_food", "more than 0", food_ref="bls:H861000", grams=0)


async def test_unknown_serving_lists_the_known_ones(mcp):
    await call(mcp, "add_serving", food_ref="bls:H861000", label="1 Block", grams=200)
    await fails(
        mcp, "log_food", "Known servings: '1 Block' = 200.0 g", food_ref="bls:H861000", serving="1 Scoop"
    )


async def test_unknown_refs_are_readable_errors(mcp):
    await fails(mcp, "log_food", "BLS has no food", food_ref="bls:ZZZ", grams=10)
    await fails(mcp, "log_food", "No stored food", food_ref="food:404", grams=10)
    await fails(mcp, "log_food", "not a food ref", food_ref="tofu", grams=10)


@respx.mock
async def test_log_food_by_off_ref_uses_its_serving(mcp):
    route_product()
    out = await call(mcp, "log_food", food_ref="off:4000000000017", serving="150 g")
    assert out["food"]["source"] == "off"
    assert out["entry"]["grams"] == 150
    assert out["entry"]["nutrients"]["protein_g"] == 16.5


@respx.mock
async def test_log_barcode_fetches_stores_and_logs(mcp, store):
    route = route_product()
    out = await call(mcp, "log_barcode", barcode="4000000000017", grams=200)
    assert out["food"]["name"] == "Testskyr Natur" and out["food"]["source"] == "off"
    assert out["entry"]["nutrients"]["kcal"] == 126.0
    again = await call(mcp, "log_barcode", barcode="4000000000017", grams=100)
    assert again["food"]["ref"] == out["food"]["ref"]
    assert route.call_count == 1  # the second scan is answered from the store


@respx.mock
async def test_log_barcode_failures_tell_the_model_what_to_do(mcp):
    respx.get(f"{OFF}/api/v2/product/4000000000999.json").respond(404, json={"status": 0})
    await fails(mcp, "log_barcode", "use log_label", barcode="4000000000999", grams=50)
    await fails(mcp, "log_barcode", "6 to 14 digits", barcode="../etc", grams=50)
    respx.get(f"{OFF}/api/v2/product/4000000000123.json").respond(503)
    await fails(mcp, "log_barcode", "having problems", barcode="4000000000123", grams=50)


# --- log_label ----------------------------------------------------------------


async def test_log_label_stores_a_label_food_and_reuses_it(mcp, store):
    args = dict(
        name="Erbsenprotein Neutral",
        brand="Beispielmarke",
        kcal_100g=380,
        protein_100g=80,
        fat_100g=6,
        carbs_100g=3,
        serving_label="1 Scoop",
        serving_grams=30,
    )
    out = await call(mcp, "log_label", serving="1 Scoop", **args)
    assert out["food"]["source"] == "label"
    assert out["entry"]["grams"] == 30
    assert out["entry"]["nutrients"]["protein_g"] == 24.0
    again = await call(mcp, "log_label", grams=15, **args)
    assert again["food"]["ref"] == out["food"]["ref"]
    assert len(store.search_foods("Erbsenprotein")) == 1
    found = await call(mcp, "search_food", query="Erbsenprotein")
    assert found["matches"][0]["servings"] == [{"label": "1 Scoop", "grams": 30.0}]


async def test_log_label_with_barcode_is_found_by_barcode_next_time(mcp):
    args = dict(
        name="Riegel", kcal_100g=400, protein_100g=30, fat_100g=15, carbs_100g=35, barcode="4000000000555"
    )
    first = await call(mcp, "log_label", grams=50, **args)
    with respx.mock:  # a stored label answers without asking Open Food Facts
        scanned = await call(mcp, "log_barcode", barcode="4000000000555", grams=50)
    assert scanned["food"]["ref"] == first["food"]["ref"]


async def test_log_label_rejects_values_that_are_not_per_100g(mcp):
    await fails(
        mcp, "log_label", "per-100 g column",
        name="X", kcal_100g=500, protein_100g=60, fat_100g=30, carbs_100g=30, grams=10,
    )  # fmt: skip
    await fails(
        mcp, "log_label", "go together",
        name="X", kcal_100g=100, protein_100g=1, fat_100g=1, carbs_100g=1, serving_label="1 Stk", grams=10,
    )  # fmt: skip


# --- log_recipe_portion -------------------------------------------------------


def route_recipe(recipe_file):
    respx.get(f"{TANDOOR}/api/property-type/").respond(json=fixture_json("tandoor", "property_types.json"))
    respx.get(f"{TANDOOR}/api/recipe/7/").respond(json=fixture_json("tandoor", recipe_file))


@respx.mock
async def test_log_recipe_portion_uses_tandoors_numbers(mcp, store):
    route_recipe("recipe_complete.json")
    out = await call(mcp, "log_recipe_portion", recipe_id=7, servings=1.5, cooklog_id=41)
    assert out["recipe"]["source"] == "tandoor"
    assert out["entry"]["nutrients"]["kcal"] == 600.0
    assert out["entry"]["servings"] == 1.5
    entry = store.get_entry(out["entry"]["id"])
    assert entry.origin_ref == "tandoor-cooklog:41" and entry.source is Source.TANDOOR


@respx.mock
async def test_same_cook_log_twice_is_reported_not_repeated(mcp, store):
    route_recipe("recipe_complete.json")
    await call(mcp, "log_recipe_portion", recipe_id=7, servings=1, cooklog_id=41)
    out = await call(mcp, "log_recipe_portion", recipe_id=7, servings=1, cooklog_id=41)
    assert out["logged"] is False and out["reason"] == "already_logged"
    assert "already logged" in out["message"]
    assert len(store.entries_between(NOW - timedelta(days=1), NOW + timedelta(days=1))) == 1


@respx.mock
async def test_without_a_cook_log_portions_can_repeat(mcp, store):
    route_recipe("recipe_complete.json")
    await call(mcp, "log_recipe_portion", recipe_id=7, servings=1)
    await call(mcp, "log_recipe_portion", recipe_id=7, servings=1)
    assert len(store.entries_between(NOW - timedelta(days=1), NOW + timedelta(days=1))) == 2


@respx.mock
async def test_incomplete_recipe_is_not_logged_and_names_the_gaps(mcp, store):
    respx.get(f"{TANDOOR}/api/property-type/").respond(json=fixture_json("tandoor", "property_types.json"))
    respx.get(f"{TANDOOR}/api/recipe/8/").respond(json=fixture_json("tandoor", "recipe_missing.json"))
    out = await call(mcp, "log_recipe_portion", recipe_id=8, servings=1, cooklog_id=5)
    assert out["logged"] is False and out["reason"] == "incomplete_recipe"
    assert out["missing_ingredients"] == ["Mystery Spice Mix", "Test Egg"]
    assert store.entries_between(NOW - timedelta(days=1), NOW + timedelta(days=1)) == []


@respx.mock
async def test_recipe_tool_errors(make):
    await fails(make(with_tandoor=False), "log_recipe_portion", "not configured", recipe_id=7, servings=1)
    respx.get(f"{TANDOOR}/api/recipe/7/").respond(401, json={})
    await fails(make(), "log_recipe_portion", "Tandoor answered 401", recipe_id=7, servings=1)


# --- log_estimate -------------------------------------------------------------


@respx.mock
async def test_estimate_uses_a_database_match_over_the_models_numbers(mcp, store):
    out = await call(
        mcp,
        "log_estimate",
        items=[
            {
                "name": "Tofu vom Teller",
                "search_name": "Tofu",
                "grams": 120,
                "confidence": "low",
                "assumptions": "half a block",
                "kcal_100g": 999,
                "protein_100g": 1,
            }
        ],
    )
    item = out["items"][0]
    assert item["basis"] == "database" and item["food"] == "Tofu"
    assert item["entry"]["nutrients"]["kcal"] == 138.0
    entry = store.get_entry(item["entry"]["id"])
    assert entry.source is Source.BLS
    assert entry.confidence.value == "low" and entry.assumptions == "half a block"
    assert out["day_so_far"]["estimated_share"] == 0.0


@respx.mock
async def test_estimate_falls_back_to_the_models_numbers_as_ai_estimate(mcp, store):
    out = await call(
        mcp,
        "log_estimate",
        items=[
            {
                "name": "Marmorkuchen",
                "search_name": "Marmorkuchen",
                "grams": 100,
                "confidence": "medium",
                "kcal_100g": 400,
                "protein_100g": 6,
                "fat_100g": 20,
            }
        ],
    )
    item = out["items"][0]
    assert item["basis"] == "estimate"
    entry = store.get_entry(item["entry"]["id"])
    assert entry.source is Source.AI_ESTIMATE and entry.food_id is None
    assert entry.nutrients.kcal == 400 and entry.nutrients.carbs_g == 0
    assert "carbohydrates not estimated" in entry.assumptions
    assert out["day_so_far"]["estimated_share"] == 1.0


@respx.mock
async def test_estimate_refuses_an_unknown_item_without_numbers(mcp, store):
    out = await call(
        mcp,
        "log_estimate",
        items=[
            {"name": "Mysteriöses Gebäck", "search_name": "Gebäck", "grams": 80, "confidence": "low"},
            {"name": "Linsen", "search_name": "Linse reif, gekocht", "grams": 200, "confidence": "high"},
            {
                "name": "Nur Kalorien",
                "search_name": "Kuchenzzz",
                "grams": 50,
                "confidence": "low",
                "kcal_100g": 300,
            },
        ],
    )
    assert [i["logged"] for i in out["items"]] == [False, True, False]
    assert "no kcal and protein estimate" in out["items"][0]["reason"]
    assert out["logged"] == 1 and out["refused"] == 2
    assert out["items"][1]["food"] == "Linse reif, gekocht"
    assert len(store.entries_between(NOW - timedelta(days=1), NOW + timedelta(days=1))) == 1


async def test_estimate_does_not_touch_open_food_facts(mcp):
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=AssertionError("no network in log_estimate"))
        out = await call(
            mcp,
            "log_estimate",
            items=[{"name": "Unbekannt", "search_name": "Unbekannt", "grams": 10, "confidence": "low"}],
        )
    assert out["refused"] == 1


# --- eaten_at -----------------------------------------------------------------


def test_parse_when_forms():
    assert parse_when(None, NOW) == NOW
    assert parse_when("", NOW) == NOW
    assert parse_when("08:15", NOW) == datetime(2026, 9, 29, 8, 15, tzinfo=BERLIN)
    assert parse_when("2026-09-28T19:30", NOW) == datetime(2026, 9, 28, 19, 30, tzinfo=BERLIN)
    assert parse_when("2026-09-28T19:30:00+00:00", NOW) == datetime(2026, 9, 28, 21, 30, tzinfo=BERLIN)


def test_bare_time_after_midnight_means_yesterday_evening():
    just_after_midnight = datetime(2026, 9, 29, 0, 20, tzinfo=BERLIN)
    assert parse_when("23:30", just_after_midnight) == datetime(2026, 9, 28, 23, 30, tzinfo=BERLIN)
    assert parse_when("00:05", just_after_midnight) == datetime(2026, 9, 29, 0, 5, tzinfo=BERLIN)
    # A few minutes ahead is clock drift, not yesterday.
    assert parse_when("00:30", just_after_midnight) == datetime(2026, 9, 29, 0, 30, tzinfo=BERLIN)


def test_utc_timestamp_lands_on_the_local_day():
    when = parse_when("2026-09-28T22:30:00Z", NOW)
    assert when.astimezone(BERLIN).date() == date(2026, 9, 29)
    assert when == datetime(2026, 9, 28, 22, 30, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["25:00", "12:75", "lunch", "2026-13-01", "2026-09-30T12:00"])
def test_parse_when_rejects_nonsense_and_the_future(bad):
    with pytest.raises(ToolError):
        parse_when(bad, NOW)


async def test_eaten_at_across_midnight_files_the_entry_on_the_right_day(make, store):
    late = make(datetime(2026, 9, 29, 0, 20, tzinfo=BERLIN))
    out = await call(late, "log_food", food_ref="bls:H861000", grams=100, eaten_at="23:30")
    assert out["entry"]["eaten_at"] == "2026-09-28T23:30+02:00"
    assert out["day_so_far"]["date"] == "2026-09-28"
    assert (await call(late, "day_summary", date="2026-09-29"))["meals"] == []
    assert len((await call(late, "day_summary", date="2026-09-28"))["meals"]) == 1


async def test_eaten_at_in_the_future_is_refused(mcp):
    await fails(
        mcp, "log_food", "in the future", food_ref="bls:H861000", grams=100, eaten_at="2026-10-01T12:00"
    )


# --- day_summary / week_summary -----------------------------------------------


async def test_day_summary_numbers_goals_meals_and_estimates(mcp):
    await call(mcp, "set_goal", nutrient="protein_g", kind="min", min=100)
    await call(mcp, "set_goal", nutrient="kcal", kind="max", max=2000)
    await call(mcp, "log_food", food_ref="bls:H861000", grams=200, eaten_at="08:00")  # 31.0 g, 230 kcal
    await call(mcp, "log_food", food_ref="bls:C133000", grams=50, eaten_at="08:30")  # 6.6 g, 174 kcal
    await call(
        mcp,
        "log_estimate",
        eaten_at="11:30",
        items=[
            {
                "name": "Kuchen",
                "search_name": "Kuchenzzz",
                "grams": 100,
                "confidence": "low",
                "kcal_100g": 400,
                "protein_100g": 5,
                "fat_100g": 20,
                "carbs_100g": 50,
            }
        ],
    )
    out = await call(mcp, "day_summary")
    assert out["date"] == "2026-09-29"
    assert out["totals"]["kcal"] == 804.0
    assert out["totals"]["protein_g"] == 42.6
    assert out["estimated_share"] == round(400 / 804, 2)
    goals = {g["nutrient"]: g for g in out["goals"]}
    assert goals["protein_g"]["met"] is False and goals["protein_g"]["remaining"] == 57.4
    assert goals["kcal"]["met"] is True and goals["kcal"]["room"] == 1196.0
    assert [m["start"] for m in out["meals"]] == ["08:00", "11:30"]
    assert out["meals"][0]["protein_g"] == 37.6
    first = out["meals"][0]["entries"][0]
    assert first["id"] and first["source"] == "bls" and first["name"] == "Tofu"
    assert out["meals"][1]["entries"][0]["source"] == "ai_estimate"


async def test_day_summary_of_an_empty_day_and_a_bad_date(mcp):
    out = await call(mcp, "day_summary", date="2026-01-01")
    assert out["meals"] == [] and out["totals"]["kcal"] == 0 and out["estimated_share"] == 0
    await fails(mcp, "day_summary", "YYYY-MM-DD", date="yesterday")


def gym_state():
    def ms(day: int, hour: int) -> int:
        return int(datetime(2026, 9, day, hour, tzinfo=BERLIN).timestamp() * 1000)

    return {
        "state": {
            "workouts": [
                {"name": "Session A", "start": ms(24, 18), "end": ms(24, 19)},
                {"name": "Session B", "start": ms(27, 9), "end": ms(27, 10)},
                {"name": "Too early", "start": ms(20, 9), "end": ms(20, 10)},
            ],
            "bodyweight": [{"d": "2026-09-25", "w": 70.5, "t": 1}, {"d": "2026-09-10", "w": 71, "t": 1}],
            "unit": "kg",
        },
        "rev": 3,
    }


@respx.mock
async def test_week_summary_adds_training_days_and_weights(mcp):
    respx.get(f"{GYM}/api/data").respond(json=gym_state())
    await call(mcp, "log_food", food_ref="bls:H861000", grams=100, eaten_at="2026-09-24T12:00")
    out = await call(mcp, "week_summary")
    assert (out["start"], out["end"]) == ("2026-09-23", "2026-09-29")
    assert len(out["days"]) == 7
    by_day = {d["date"]: d for d in out["days"]}
    assert by_day["2026-09-24"]["totals"]["kcal"] == 115.0 and by_day["2026-09-24"]["training"] is True
    assert by_day["2026-09-25"]["training"] is False
    assert [w["name"] for w in out["workouts"]] == ["Session A", "Session B"]
    assert out["body_weights"] == [{"date": "2026-09-25", "kg": 70.5}]
    assert out["days_logged"] == 1 and out["average_per_logged_day"]["protein_g"] == 15.5
    assert out["notes"] == []


@respx.mock
async def test_week_summary_drops_gym_fields_when_open_gym_fails(mcp):
    respx.get(f"{GYM}/api/data").respond(401, json={})
    out = await call(mcp, "week_summary", start="2026-09-22")
    assert out["start"] == "2026-09-22" and len(out["days"]) == 7
    assert "workouts" not in out and "body_weights" not in out
    assert all("training" not in d for d in out["days"])
    assert "pair again" in out["notes"][0]


async def test_week_summary_without_open_gym(make):
    out = await call(make(with_gym=False), "week_summary")
    assert "workouts" not in out and out["notes"] == []


# --- corrections and goals ----------------------------------------------------


async def test_update_and_delete_entry(mcp, store):
    logged = await call(mcp, "log_food", food_ref="bls:H861000", grams=100)
    entry_id = logged["entry"]["id"]
    updated = await call(mcp, "update_entry", entry_id=entry_id, grams=200, eaten_at="09:00")
    assert updated["entry"]["nutrients"]["kcal"] == 230.0
    assert updated["entry"]["eaten_at"] == "2026-09-29T09:00+02:00"
    deleted = await call(mcp, "delete_entry", entry_id=entry_id)
    assert deleted["deleted"] is True and deleted["entry"]["name"] == "Tofu"
    await fails(mcp, "delete_entry", "Nothing stored", entry_id=entry_id)
    await fails(mcp, "update_entry", "Nothing stored", entry_id=entry_id, grams=5)


async def test_update_entry_errors(mcp):
    entry_id = (await call(mcp, "log_food", food_ref="bls:H861000", grams=100))["entry"]["id"]
    await fails(mcp, "update_entry", "Give grams", entry_id=entry_id)
    await fails(mcp, "update_entry", "positive", entry_id=entry_id, grams=-1)
    await fails(mcp, "update_entry", "no servings to rescale", entry_id=entry_id, servings=2)


async def test_set_goal_validates_bounds_and_replaces_by_date(mcp, store):
    await fails(mcp, "set_goal", "needs its bounds", nutrient="protein_g", kind="band", min=100)
    out = await call(
        mcp, "set_goal", nutrient="protein_g", kind="band", min=100, max=140, valid_from="2026-09-01"
    )
    assert out["goal"]["valid_from"] == "2026-09-01"
    await call(mcp, "set_goal", nutrient="protein_g", kind="min", min=120)  # from today
    assert store.goals_on(date(2026, 9, 15))[0].kind.value == "band"
    assert store.goals_on(date(2026, 9, 29))[0].min == 120
    with pytest.raises(ToolError):
        await mcp.call_tool("set_goal", {"nutrient": "sodium", "kind": "min", "min": 1})


async def test_add_serving_updates_the_same_label(mcp):
    await call(mcp, "add_serving", food_ref="bls:H861000", label="1 Scoop", grams=30)
    out = await call(mcp, "add_serving", food_ref="bls:H861000", label="1 Scoop", grams=32)
    assert out["servings"] == [{"label": "1 Scoop", "grams": 32.0}]
    assert out["food"]["ref"].startswith("food:")


@respx.mock
async def test_an_unexpected_off_status_is_a_readable_error(mcp):
    respx.get(f"{OFF}/api/v2/product/4000000000777.json").respond(403)
    await fails(mcp, "log_barcode", "403", barcode="4000000000777", grams=10)


# --- suggest_foods -----------------------------------------------------------


def stock(store, name, kcal, protein, *, servings=()):
    return store.upsert_food(
        FoodCandidate(
            name=name, source=Source.MANUAL, per_100g=Nutrients(kcal, protein, 1, 5), servings=servings
        )
    )


def eat(store, food, grams, days_ago=1):
    return store.log_entry(
        name=food.name,
        nutrients=food.per_100g.for_grams(grams),
        eaten_at=NOW - timedelta(days=days_ago),
        source=food.source,
        origin=Origin.CHAT,
        grams=grams,
        food_id=food.id,
    )


async def test_suggest_foods_with_no_history_is_empty_and_says_so(mcp):
    out = await call(mcp, "suggest_foods", protein_g=30)
    assert out["suggestions"] == []
    assert "nothing to suggest" in out["note"]


async def test_suggest_foods_ranks_by_frequency_and_density_with_usual_portion(mcp, store):
    tofu = stock(store, "Smoked Tofu", 150, 15, servings=(Serving("1 Block", 200),))
    lentils = stock(store, "Red Lentils", 350, 25)
    rice = stock(store, "White Rice", 350, 7)
    for grams in (180, 200, 220):
        eat(store, tofu, grams)
    eat(store, lentils, 60)
    eat(store, rice, 80)
    out = await call(mcp, "suggest_foods", protein_g=40)
    assert [s["name"] for s in out["suggestions"]] == ["Smoked Tofu", "Red Lentils", "White Rice"]
    top = out["suggestions"][0]
    assert top["ref"] == f"food:{tofu.id}" and top["times_eaten"] == 3
    assert top["portion_g"] == 200 and top["serving"] == "1 Block"
    assert top["kcal"] == 300 and top["protein_g"] == 30
    assert top["closes_gap_pct"] == 75 and top["protein_per_100kcal"] == 10
    assert out["note"] is None


async def test_suggest_foods_ignores_old_entries_and_caps_the_share_at_100(mcp, store):
    seitan = stock(store, "Seitan", 120, 25)
    old = stock(store, "Chickpea Flour", 380, 22)
    eat(store, seitan, 200)
    eat(store, old, 100, days_ago=45)
    out = await call(mcp, "suggest_foods", protein_g=20)
    assert [s["name"] for s in out["suggestions"]] == ["Seitan"]
    assert out["suggestions"][0]["closes_gap_pct"] == 100


async def test_suggest_foods_uses_quick_items_and_respects_kcal_max(mcp, store):
    peanuts = stock(store, "Peanut Butter", 600, 25)
    edamame = stock(store, "Edamame", 120, 12)
    store.add_quick_item(peanuts.id, 30, "PB spoon")
    store.add_quick_item(edamame.id, 100, "Edamame cup")
    out = await call(mcp, "suggest_foods", protein_g=15, kcal_max=150)
    assert [s["name"] for s in out["suggestions"]] == ["Edamame"]
    assert out["suggestions"][0]["portion_basis"] == "quick item"
    assert out["suggestions"][0]["times_eaten"] == 0
    tight = await call(mcp, "suggest_foods", protein_g=15, kcal_max=50)
    assert tight["suggestions"] == [] and "kcal_max" in tight["note"]


async def test_suggest_foods_respects_limit_and_skips_protein_free_foods(mcp, store):
    for i in range(4):
        eat(store, stock(store, f"Bean {i}", 100, 8 + i), 100)
    eat(store, stock(store, "Sugar", 400, 0), 10)
    out = await call(mcp, "suggest_foods", protein_g=20, limit=2)
    assert len(out["suggestions"]) == 2
    everything = await call(mcp, "suggest_foods", protein_g=20, limit=10)
    assert "Sugar" not in [s["name"] for s in everything["suggestions"]]


# --- log_again ---------------------------------------------------------------


async def test_log_again_copies_entries_to_the_given_time(mcp, store):
    oats = stock(store, "Oat Flakes", 370, 13)
    soy = stock(store, "Soy Drink", 40, 3.5)
    first = eat(store, oats, 60)
    second = eat(store, soy, 250)
    out = await call(mcp, "log_again", entry_ids=[first.id, second.id], eaten_at="08:00")
    assert out["logged"] == 2
    copies = [store.get_entry(e["id"]) for e in out["entries"]]
    assert [c.id for c in copies] == [second.id + 1, second.id + 2]
    assert [c.name for c in copies] == ["Oat Flakes", "Soy Drink"]
    assert copies[0].nutrients == first.nutrients and copies[1].nutrients == second.nutrients
    assert (copies[0].grams, copies[0].food_id, copies[0].source) == (60, oats.id, Source.MANUAL)
    assert all(c.eaten_at == datetime(2026, 9, 29, 8, 0, tzinfo=BERLIN) for c in copies)
    assert out["day_so_far"]["protein_g"] == round(
        copies[0].nutrients.protein_g + copies[1].nutrients.protein_g, 1
    )
    assert store.get_entry(first.id) == first


async def test_log_again_defaults_to_now_and_drops_origin_ref(mcp, store):
    original = store.log_entry(
        name="Chili sin Carne",
        nutrients=Nutrients(500, 30, 10, 60),
        eaten_at=NOW - timedelta(days=1),
        source=Source.TANDOOR,
        origin=Origin.TANDOOR,
        servings=1,
        origin_ref="tandoor-cooklog:9",
    )
    out = await call(mcp, "log_again", entry_ids=[original.id])
    copy = store.get_entry(out["entries"][0]["id"])
    assert copy.eaten_at == NOW and copy.origin_ref is None
    assert (copy.servings, copy.source, copy.origin) == (1, Source.TANDOOR, Origin.CHAT)


async def test_log_again_logs_nothing_when_one_id_is_unknown(mcp, store):
    entry = eat(store, stock(store, "Oat Flakes", 370, 13), 60)
    await fails(mcp, "log_again", "Nothing stored", entry_ids=[entry.id, 999])
    assert len(store.entries_between(NOW - timedelta(days=3), NOW + timedelta(days=1))) == 1


async def test_log_again_refuses_a_future_time(mcp, store):
    entry = eat(store, stock(store, "Oat Flakes", 370, 13), 60)
    await fails(mcp, "log_again", "future", entry_ids=[entry.id], eaten_at="2026-10-05T08:00")


# --- recipe_nutrition --------------------------------------------------------


@respx.mock
async def test_recipe_nutrition_ranks_inputs_and_reports_each_recipe_alone(mcp):
    respx.get(f"{TANDOOR}/api/property-type/").respond(json=fixture_json("tandoor", "property_types.json"))
    respx.get(f"{TANDOOR}/api/recipe/7/").respond(json=fixture_json("tandoor", "recipe_complete.json"))
    respx.get(f"{TANDOOR}/api/recipe/8/").respond(json=fixture_json("tandoor", "recipe_missing.json"))
    respx.get(f"{TANDOOR}/api/recipe/9/").respond(404, json={})
    out = await call(mcp, "recipe_nutrition", recipe_ids=[7, 8, 9, 7])
    complete, gappy, broken = out["recipes"]
    assert complete["recipe_id"] == 7 and complete["complete"] is True and complete["missing"] == []
    assert complete["per_serving"]["kcal"] == 400.0
    assert complete["protein_per_100kcal"] == round(
        complete["per_serving"]["protein_g"] / complete["per_serving"]["kcal"] * 100, 1
    )
    assert gappy["complete"] is False and gappy["missing"] == ["Mystery Spice Mix", "Test Egg"]
    assert broken["recipe_id"] == 9 and "404" in broken["error"] and "per_serving" not in broken


@respx.mock
async def test_recipe_nutrition_limits_and_configuration(make):
    await fails(make(with_tandoor=False), "recipe_nutrition", "not configured", recipe_ids=[7])
    await fails(make(), "recipe_nutrition", "at most 20", recipe_ids=list(range(1, 22)))
    respx.get(f"{TANDOOR}/api/recipe/7/").respond(json=fixture_json("tandoor", "recipe_complete.json"))
    respx.get(f"{TANDOOR}/api/property-type/").respond(401, json={})
    out = await call(make(), "recipe_nutrition", recipe_ids=[7])
    assert "401" in out["recipes"][0]["error"]
