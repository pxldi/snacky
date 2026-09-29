import json
from pathlib import Path

import httpx
import pytest
import respx

from snacky.model import Source
from snacky.sources.off import OffClient, OffUnavailable

FIXTURES = Path(__file__).parent / "fixtures" / "off"
BASE = "https://off.test"
SEARCH = "https://search.test"
UA = "snacky-test/0 (test@example.invalid)"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    c = OffClient(UA, base_url=BASE, search_url=SEARCH)
    yield c
    await c.aclose()


@respx.mock
async def test_full_product(client):
    route = respx.get(f"{BASE}/api/v2/product/4000000000017.json").respond(json=fixture("product_full.json"))
    food = await client.by_barcode("4000000000017")
    assert food is not None
    assert food.name == "Testskyr Natur"
    assert food.brand == "Beispielhof"
    assert food.source is Source.OFF
    assert food.source_ref == "4000000000017"
    assert (food.per_100g.kcal, food.per_100g.protein_g) == (63, 11)
    assert (food.per_100g.fat_g, food.per_100g.carbs_g, food.per_100g.fibre_g) == (0.2, 4, 0.5)
    assert [(s.label, s.grams) for s in food.servings] == [("150 g", 150)]
    assert food.extra["sugars_100g"] == 4
    assert "energy-kcal_100g" not in food.extra
    assert "fields=" in str(route.calls[0].request.url)


@respx.mock
async def test_kj_only_is_converted(client):
    respx.get(f"{BASE}/api/v2/product/4000000000024.json").respond(json=fixture("product_kj_only.json"))
    food = await client.by_barcode("4000000000024")
    assert food is not None
    assert food.per_100g.kcal == pytest.approx(1674 / 4.184)
    assert food.name == "Test Crackers"
    assert food.per_100g.fibre_g is None
    assert food.servings == ()


@respx.mock
async def test_missing_protein_is_none(client):
    respx.get(f"{BASE}/api/v2/product/4000000000031.json").respond(json=fixture("product_no_protein.json"))
    assert await client.by_barcode("4000000000031") is None


@respx.mock
@pytest.mark.parametrize("status", [200, 404])
async def test_unknown_barcode_is_none(client, status):
    respx.get(f"{BASE}/api/v2/product/4000000000048.json").respond(
        status, json=fixture("product_unknown.json")
    )
    assert await client.by_barcode("4000000000048") is None


@respx.mock
async def test_search_skips_incomplete_and_maps_fields(client):
    route = respx.get(f"{SEARCH}/search").respond(json=fixture("search_mixed.json"))
    found = await client.search("quark", limit=10)
    assert [f.source_ref for f in found] == ["4000000000055", "4000000000062"]
    assert found[0].name == "Testquark"
    assert found[0].brand == "Beispielhof"
    nuts = found[1]
    assert nuts.brand == "Musternuss"
    assert nuts.per_100g.kcal == 610
    assert nuts.per_100g.fibre_g == 7
    assert nuts.servings[0].grams == 30
    assert route.call_count == 1
    params = route.calls[0].request.url.params
    assert params["q"] == 'quark countries_tags:"en:germany"'
    assert params["langs"] == "de"
    assert "fields" in params


@respx.mock
async def test_search_falls_back_without_country_filter(client):
    def answer(request: httpx.Request) -> httpx.Response:
        if "countries_tags" in request.url.params["q"]:
            return httpx.Response(200, json={"hits": []})
        return httpx.Response(200, json=fixture("search_mixed.json"))

    route = respx.get(f"{SEARCH}/search").mock(side_effect=answer)
    found = await client.search("quark")
    assert len(found) == 2
    assert [c.request.url.params["q"] for c in route.calls] == ['quark countries_tags:"en:germany"', "quark"]


@respx.mock
async def test_search_respects_limit(client):
    respx.get(f"{SEARCH}/search").respond(json=fixture("search_mixed.json"))
    assert len(await client.search("x", limit=1)) == 1


@respx.mock
async def test_rate_limit_raises(client):
    respx.get(f"{BASE}/api/v2/product/1.json").respond(429)
    with pytest.raises(OffUnavailable, match="rate-limiting"):
        await client.by_barcode("1")


@respx.mock
async def test_server_error_raises_on_search(client):
    respx.get(f"{SEARCH}/search").respond(503)
    with pytest.raises(OffUnavailable):
        await client.search("x")


@respx.mock
async def test_timeout_raises(client):
    respx.get(f"{BASE}/api/v2/product/1.json").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(OffUnavailable, match="in time"):
        await client.by_barcode("1")


@respx.mock
async def test_user_agent_sent(client):
    route = respx.get(f"{BASE}/api/v2/product/4000000000017.json").respond(json=fixture("product_full.json"))
    await client.by_barcode("4000000000017")
    assert route.calls[0].request.headers["user-agent"] == UA


@respx.mock
async def test_aclose_only_closes_owned_client():
    shared = httpx.AsyncClient()
    await OffClient(UA, http=shared).aclose()
    assert not shared.is_closed
    await shared.aclose()
    owner = OffClient(UA)
    await owner.aclose()
    assert owner._http.is_closed
