import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from snacky.model import BodyWeight, Workout
from snacky.sources import opengym
from snacky.sources.opengym import OpenGymClient, OpenGymError

FIXTURES = Path(__file__).parent / "fixtures" / "opengym"
BASE = "https://gym.example.test"
START, END = date(2026, 8, 10), date(2026, 8, 31)


@pytest.fixture(autouse=True)
def berlin(monkeypatch):
    # The fixture's timestamps were made for this zone.
    monkeypatch.setattr(opengym, "TZ", ZoneInfo("Europe/Berlin"))


def load(name: str = "data.json") -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as http:
        yield OpenGymClient(BASE + "/", "test-token", http)


@respx.mock
async def test_workouts_filter_range_edges_and_skip_unfinished(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load()))
    got = await client.workouts_between(START, END)
    assert [w.name for w in got] == ["Pull A", "Legs", "Late Push", "Night Pull", "Last Day"]
    # start is inclusive: midnight of the first day counts. end is exclusive.
    assert got[0] == Workout(day=date(2026, 8, 10), name="Pull A", duration_min=45.0)
    assert "Unfinished" not in [w.name for w in got]
    assert "Excluded" not in [w.name for w in got]


@respx.mock
async def test_duration_in_minutes(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load()))
    got = {w.name: w for w in await client.workouts_between(START, END)}
    assert got["Legs"].duration_min == 75.5


@respx.mock
async def test_local_date_rule_around_midnight(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load()))
    got = {w.name: w.day for w in await client.workouts_between(START, END)}
    # 23:30 local is 21:30 UTC, and 00:15 local is 22:15 UTC on the previous day.
    assert got["Late Push"] == date(2026, 8, 20)
    assert got["Night Pull"] == date(2026, 8, 21)
    assert got["Last Day"] == date(2026, 8, 30)


@respx.mock
async def test_day_follows_configured_zone(client, monkeypatch):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load()))
    monkeypatch.setattr(opengym, "TZ", ZoneInfo("UTC"))
    got = {w.name: w.day for w in await client.workouts_between(START, END)}
    assert got["Night Pull"] == date(2026, 8, 20)


@respx.mock
async def test_workout_without_start_falls_back_to_device_day(client):
    state = {"workouts": [{"d": "2026-08-12", "name": "Old import", "end": 1}]}
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json={"state": state}))
    got = await client.workouts_between(START, END)
    assert got == [Workout(day=date(2026, 8, 12), name="Old import", duration_min=None)]


@respx.mock
async def test_body_weights_kg_range_edges(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load()))
    got = await client.body_weights_between(START, END)
    assert got == [
        BodyWeight(day=date(2026, 8, 10), kg=80.0),
        BodyWeight(day=date(2026, 8, 15), kg=79.6),
        BodyWeight(day=date(2026, 8, 30), kg=79.2),
    ]


@respx.mock
async def test_body_weights_converted_from_pounds(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load("data_lb.json")))
    got = await client.body_weights_between(START, END)
    assert [(b.day, b.kg) for b in got] == [(date(2026, 8, 10), 80.01), (date(2026, 8, 11), 49.99)]


@respx.mock
async def test_missing_unit_means_kg(client):
    state = {"bodyweight": [{"d": "2026-08-10", "w": 81.5, "t": 1}]}
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json={"state": state}))
    assert (await client.body_weights_between(START, END))[0].kg == 81.5


@respx.mock
async def test_empty_account_returns_nothing(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json={"state": None, "rev": 0}))
    assert await client.workouts_between(START, END) == []
    assert await client.body_weights_between(START, END) == []


@respx.mock
async def test_malformed_entries_are_skipped(client):
    state = {
        "workouts": [None, 3, {"end": 5}, {"start": "x", "end": 5, "d": "nope"}],
        "bodyweight": [None, {"d": "2026-08-12"}, {"d": "bad", "w": 80}, {"d": "2026-08-12", "w": True}],
    }
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json={"state": state}))
    assert await client.workouts_between(START, END) == []
    assert await client.body_weights_between(START, END) == []


@respx.mock
async def test_bearer_header_and_url(client):
    route = respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, json=load()))
    await client.workouts_between(START, END)
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
@pytest.mark.parametrize("status", [401, 403])
async def test_revoked_token_message(client, status):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(status, json={"error": "not signed in"}))
    with pytest.raises(OpenGymError, match="revoked or expired; pair again"):
        await client.workouts_between(START, END)
    with pytest.raises(OpenGymError, match="pair again"):
        await client.body_weights_between(START, END)


@respx.mock
async def test_server_error(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(500, json={"error": "server error"}))
    with pytest.raises(OpenGymError, match="HTTP 500"):
        await client.workouts_between(START, END)


@respx.mock
async def test_connection_failure(client):
    respx.get(f"{BASE}/api/data").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(OpenGymError, match="could not reach openGym"):
        await client.workouts_between(START, END)


@respx.mock
async def test_non_json_body(client):
    respx.get(f"{BASE}/api/data").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(OpenGymError, match="not its state document"):
        await client.workouts_between(START, END)


@respx.mock
async def test_owned_client_closes_and_borrowed_stays_open():
    owned = OpenGymClient(BASE, "t")
    await owned.aclose()
    assert owned._http.is_closed
    async with httpx.AsyncClient() as http:
        borrowed = OpenGymClient(BASE, "t", http)
        await borrowed.aclose()
        assert not http.is_closed
