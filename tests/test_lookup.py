"""Lookup order and de-duplication. Nothing here touches the network."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from snacky.lookup import Lookup, LookupFailed, is_good_match
from snacky.model import FoodCandidate, Nutrients, Source
from snacky.sources.bls import BlsIndex, build
from snacky.sources.off import OffClient
from snacky.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
OFF = "https://world.openfoodfacts.org"
SEARCH = "https://search.openfoodfacts.org"


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
async def lookup(store, bls_file):
    bls = BlsIndex(bls_file)
    off = OffClient("snacky-test")
    yield Lookup(store, bls, off)
    bls.close()
    await off.aclose()


def refs(matches):
    return [m.ref for m in matches]


def off_product(name):
    return (FIXTURES / "off" / name).read_text()


@respx.mock
async def test_stored_foods_come_before_bls(lookup, store):
    stored = store.upsert_food(
        FoodCandidate("Tofu Natur Eigenmarke", Source.MANUAL, Nutrients(120, 14, 6, 1))
    )
    found = await lookup.search("Tofu", limit=4)
    assert found[0].ref == f"food:{stored.id}"
    assert found[0].food_id == stored.id
    assert all(m.ref.startswith("bls:") for m in found[1:])
    assert refs(found)[1] == "bls:H861000"


@respx.mock
async def test_bls_hit_already_stored_is_listed_once(lookup):
    food = await lookup.by_ref("bls:H861000")
    found = await lookup.search("Tofu", limit=5)
    listed = refs(found)
    assert listed.count(f"food:{food.id}") == 1
    assert "bls:H861000" not in listed


@respx.mock
async def test_off_is_skipped_when_local_results_fill_the_limit(lookup):
    search = respx.get(f"{SEARCH}/search").respond(json={"hits": []})
    found = await lookup.search("Tofu", limit=3)
    assert len(found) == 3
    assert not search.called


@respx.mock
async def test_off_fills_up_when_local_results_are_short(lookup):
    respx.get(f"{SEARCH}/search").respond(json=json.loads(off_product("search_mixed.json")))
    found = await lookup.search("quark", limit=5)
    assert refs(found)[0] == "off:4000000000055"
    assert found[0].candidate.source is Source.OFF
    assert found[0].food_id is None


@respx.mock
async def test_off_hit_already_stored_is_listed_once(lookup, store):
    stored = store.upsert_food(
        FoodCandidate("Test Quark", Source.OFF, Nutrients(70, 12, 0.2, 4), source_ref="4000000000055")
    )
    respx.get(f"{SEARCH}/search").respond(json=json.loads(off_product("search_mixed.json")))
    found = await lookup.search("quark", limit=5)
    assert refs(found).count(f"food:{stored.id}") == 1
    assert "off:4000000000055" not in refs(found)


@respx.mock
async def test_off_outage_keeps_local_results_and_adds_a_note(lookup):
    respx.get(f"{SEARCH}/search").mock(side_effect=httpx.ConnectError("down"))
    found, notes = await lookup.search_with_notes("Linse", limit=15)
    assert found and all(m.ref.startswith("bls:") for m in found)
    assert len(notes) == 1 and "Open Food Facts" in notes[0]
    assert refs(await lookup.search("Linse", limit=15)) == refs(found)


async def test_search_without_bls_or_off(store):
    plain = Lookup(store, None, None)
    assert await plain.search("Tofu") == []
    with pytest.raises(LookupFailed, match="BLS"):
        await plain.by_ref("bls:H861000")


async def test_by_ref_stores_bls_food_once(lookup, store):
    first = await lookup.by_ref("bls:H861000")
    second = await lookup.by_ref("bls:H861000")
    assert first.id == second.id
    assert first.source is Source.BLS and first.per_100g.protein_g == pytest.approx(15.51)
    assert (await lookup.by_ref(f"food:{first.id}")).name == "Tofu"
    assert [f.id for f in store.search_foods("Tofu")][:1] == [first.id]


@respx.mock
async def test_by_ref_off_uses_barcode_path(lookup):
    respx.get(f"{OFF}/api/v2/product/4000000000017.json").respond(
        json=json.loads(off_product("product_full.json"))
    )
    food = await lookup.by_ref("off:4000000000017")
    assert food.source is Source.OFF and food.brand == "Beispielhof"


@pytest.mark.parametrize("ref", ["", "tofu", "food:", "food:x", "food:999", "bls:NOPE", "x:1"])
async def test_by_ref_rejects_bad_refs(lookup, ref):
    with pytest.raises(LookupFailed):
        await lookup.by_ref(ref)


@respx.mock
async def test_barcode_prefers_stored_food_and_skips_off(lookup, store):
    route = respx.get(f"{OFF}/api/v2/product/4000000000017.json").respond(
        json=json.loads(off_product("product_full.json"))
    )
    first = await lookup.barcode("4000000000017")
    again = await lookup.barcode("4000000000017")
    assert first is not None and again is not None and first.id == again.id
    assert route.call_count == 1


@respx.mock
async def test_barcode_prefers_a_stored_label_over_off(lookup, store):
    label = store.upsert_food(
        FoodCandidate(
            "Skyr laut Etikett", Source.LABEL, Nutrients(60, 11, 0.2, 4), source_ref="4000000000017"
        )
    )
    route = respx.get(f"{OFF}/api/v2/product/4000000000017.json")
    found = await lookup.barcode("4000000000017")
    assert found is not None and found.id == label.id
    assert not route.called


@respx.mock
async def test_unknown_barcode_is_none(lookup):
    respx.get(f"{OFF}/api/v2/product/4000000000999.json").respond(404, json={"status": 0})
    assert await lookup.barcode("4000000000999") is None


@pytest.mark.parametrize(
    ("query", "name", "good"),
    [
        ("Tofu", "Tofu", True),
        ("Tofu", "Tofu gebacken", True),
        ("Haferflocken", "Hafer Flocken", True),
        ("Linsen", "Linse reif", True),
        ("Sojadrink", "Kaffee (Getränk) mit Sojadrink, ungesüßt", False),
        ("Tofu", "Seidentofu", False),
        ("", "Tofu", False),
    ],
)
def test_is_good_match(query, name, good):
    assert is_good_match(query, name) is good
