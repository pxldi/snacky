"""Web UI and JSON API, driven through Starlette's TestClient. No network."""

import asyncio
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

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
    Workout,
)
from snacky.sources.opengym import OpenGymError
from snacky.store import Store
from snacky.web import app as web_app
from snacky.web import create_app

BERLIN = ZoneInfo("Europe/Berlin")
SAME_SITE = {"Origin": "http://testserver"}
TODAY = "2026-09-29"  # a Tuesday


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(config, "TZ", BERLIN)
    monkeypatch.setattr(config, "MEAL_GAP", timedelta(minutes=90))
    monkeypatch.setattr(web_app, "_now", lambda: datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN))
    monkeypatch.delenv("SNACKY_MEAL_PROTEIN_MIN", raising=False)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def food(store):
    return store.upsert_food(
        FoodCandidate(
            name="Tofu natur",
            source=Source.OFF,
            per_100g=Nutrients(150, 11, 7, 1, 0),
            source_ref="demo-1",
            servings=(Serving("1 Block", 200),),
        )
    )


@pytest.fixture
def seeded(store, food):
    store.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 1, 1), min=120))
    store.set_goal(Goal("kcal", GoalKind.BAND, date(2026, 1, 1), min=2200, max=2600))
    breakfast = store.log_entry(
        name="Tofu natur",
        nutrients=food.per_100g.for_grams(250),
        eaten_at=at(TODAY, 8, 0),
        source=Source.OFF,
        origin=Origin.CHAT,
        grams=250,
        food_id=food.id,
    )
    estimate = store.log_entry(
        name="Pasta im Restaurant",
        nutrients=Nutrients(700, 24, 20, 100),
        eaten_at=at(TODAY, 12, 30),
        source=Source.AI_ESTIMATE,
        origin=Origin.CHAT,
        servings=1,
        confidence=Confidence.LOW,
        assumptions="Eine normale Portion.",
    )
    return breakfast, estimate


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


@pytest.fixture
def writer(store):
    """A client that sends the Origin header a browser sends on a form post."""
    return TestClient(create_app(store), headers=SAME_SITE, follow_redirects=False)


class FakeGym:
    def __init__(self, workouts=None, error=None):
        self.workouts, self.error, self.calls = workouts or [], error, []

    async def workouts_between(self, start, end):
        self.calls.append((start, end))
        if self.error:
            raise self.error
        return [w for w in self.workouts if start <= w.day < end]


def at(day: str, hh: int, mm: int = 0) -> datetime:
    y, m, d = (int(p) for p in day.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=BERLIN)


# Pages


def test_health(client):
    assert client.get("/health").text == "ok"


def test_pages_render_empty(client):
    day = client.get("/")
    assert day.status_code == 200
    assert "Noch nichts drin. Schreib Clanky, was du gegessen hast." in day.text
    assert "Kein Proteinziel gesetzt." in day.text
    assert "Noch keine Schnellwahl" in day.text
    week = client.get("/week")
    assert week.status_code == 200
    assert "Noch nichts eingetragen" in week.text
    quick = client.get("/quick")
    assert quick.status_code == 200
    assert "Noch keine Schnellwahl" in quick.text


def test_day_page_with_data(client, seeded):
    page = client.get("/").text
    assert "Bundeslebensmittelschlüssel 4.0, Max Rubner-Institut, CC BY 4.0" in page
    assert "Open Food Facts, ODbL" in page
    assert re.search(r'class="claim-num">52<', page)  # 27.5 + 24 = 51.5 g protein
    assert "Ziel</span> 120&nbsp;g" in page
    assert "Noch 69 g" in page  # the gap, next to the total
    assert "2.200–2.600" in page
    assert "Tofu natur" in page and "250\u00a0g" in page and "Open Food Facts" in page
    assert "Pasta im Restaurant" in page
    assert "geschätzt, unsicher" in page and "≈ 24\u00a0g" in page
    assert "davon ≈&nbsp;47&nbsp;% des Proteins geschätzt" in page  # 24 of 51.5 g protein
    assert "erreicht" not in page and "unter&nbsp;" not in page  # no per-meal target without the env var


def test_estimate_marker_for_medium_confidence(client, store):
    store.log_entry(
        name="Etikett",
        nutrients=Nutrients(100, 10, 1, 1),
        eaten_at=at(TODAY, 9),
        source=Source.LABEL,
        origin=Origin.CHAT,
        grams=100,
        confidence=Confidence.MEDIUM,
    )
    assert "geschätzt, eher sicher" in client.get("/").text


def test_no_estimate_marker_for_high_confidence(client, store):
    store.log_entry(
        name="Sicher",
        nutrients=Nutrients(100, 10, 1, 1),
        eaten_at=at(TODAY, 9),
        source=Source.LABEL,
        origin=Origin.CHAT,
        grams=100,
        confidence=Confidence.HIGH,
    )
    assert "geschätzt" not in client.get("/").text


def test_meal_protein_target(client, seeded, monkeypatch):
    monkeypatch.setenv("SNACKY_MEAL_PROTEIN_MIN", "25")
    page = client.get("/").text
    assert "ab&nbsp;25&nbsp;g" in page  # 27.5 g breakfast
    assert "unter&nbsp;25&nbsp;g" in page  # 24 g lunch


def test_invalid_meal_target_is_ignored(client, seeded, monkeypatch):
    monkeypatch.setenv("SNACKY_MEAL_PROTEIN_MIN", "lots")
    assert "unter&nbsp;" not in client.get("/").text


def test_day_navigation(client, seeded):
    page = client.get("/?day=2026-09-28").text
    assert "/?day=2026-09-27" in page and "/?day=2026-09-29" in page
    assert "An diesem Tag wurde nichts eingetragen." in page
    assert 'aria-label="Schnell eintragen"' not in page  # quick buttons log "now", so only on today
    assert client.get("/?day=nonsense").status_code == 400


def test_pages_have_no_inline_script_or_style(client, seeded, store):
    store.add_quick_item(1, 100, "Tofu")
    for path in ["/", "/week", "/quick", "/quick?q=tofu", "/entries/1", "/entries/1/delete"]:
        page = client.get(path).text
        assert " style=" not in page and "<style" not in page, path
        assert not re.search(r"<script(?![^>]*\bsrc=)", page), path
        assert not re.search(r"(src|href)=\"https?://", page), path


def test_security_headers(client):
    response = client.get("/")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_static_files(client):
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_html_is_escaped(client, store):
    store.log_entry(
        name="<script>alert(1)</script>",
        nutrients=Nutrients(1, 1, 1, 1),
        eaten_at=at(TODAY, 9),
        source=Source.MANUAL,
        origin=Origin.CHAT,
        grams=10,
    )
    page = client.get("/").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_unknown_routes_are_404(client):
    assert client.get("/entries/999").status_code == 404
    assert client.get("/nowhere").status_code == 404


# Entry edit and delete


def test_edit_page_shows_details(client, seeded):
    page = client.get("/entries/2").text
    assert "Pasta im Restaurant" in page
    assert "Eine normale Portion." in page
    assert 'name="amount"' in page and "Portionen" in page
    assert "Schätzung:" in page  # the one-line explanation


def test_update_grams_and_time(writer, store, seeded):
    breakfast, _ = seeded
    response = writer.post(
        f"/entries/{breakfast.id}", data={"amount": "500", "day": TODAY, "time": "09:15", "back": "/"}
    )
    assert response.status_code == 303 and response.headers["location"] == "/"
    updated = store.get_entry(breakfast.id)
    assert updated.grams == 500
    assert updated.nutrients.protein_g == pytest.approx(55)
    assert updated.eaten_at.hour == 9 and updated.eaten_at.minute == 15


def test_update_accepts_decimal_comma(writer, store, seeded):
    breakfast, _ = seeded
    writer.post(f"/entries/{breakfast.id}", data={"amount": "125,5", "day": TODAY, "time": "08:00"})
    assert store.get_entry(breakfast.id).grams == 125.5


def test_update_servings(writer, store, seeded):
    _, estimate = seeded
    writer.post(f"/entries/{estimate.id}", data={"amount": "2", "day": TODAY, "time": "12:30"})
    assert store.get_entry(estimate.id).nutrients.protein_g == pytest.approx(48)


@pytest.mark.parametrize("amount", ["", "abc", "0", "-5", "nan"])
def test_update_rejects_bad_amount(writer, store, seeded, amount):
    breakfast, _ = seeded
    response = writer.post(f"/entries/{breakfast.id}", data={"amount": amount, "day": TODAY, "time": "08:00"})
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert store.get_entry(breakfast.id).grams == 250


def test_update_rejects_bad_time(writer, seeded):
    response = writer.post("/entries/1", data={"amount": "100", "day": TODAY, "time": "late"})
    assert response.status_code == 400


def test_update_ignores_offsite_back_target(writer, seeded):
    response = writer.post(
        "/entries/1", data={"amount": "250", "day": TODAY, "time": "08:00", "back": "https://evil.example/"}
    )
    assert response.headers["location"] == f"/?day={TODAY}"


def test_delete_needs_confirmation_page_then_post(writer, store, seeded):
    breakfast, _ = seeded
    assert "Eintrag löschen?" in writer.get(f"/entries/{breakfast.id}/delete").text
    assert store.get_entry(breakfast.id)  # the GET deleted nothing
    response = writer.post(f"/entries/{breakfast.id}/delete", data={})
    assert response.status_code == 303
    assert len(store.entries_between(at(TODAY, 0), at(TODAY, 23))) == 1


def test_delete_missing_entry(writer):
    assert writer.post("/entries/99/delete", data={}).status_code == 404


# Quick items


def test_quick_add_search_and_remove(writer, store, food):
    assert "Tofu natur" in writer.get("/quick?q=tof").text
    assert "Nichts gefunden" in writer.get("/quick?q=zzzz").text
    response = writer.post("/quick", data={"food_id": str(food.id), "grams": "250", "label": "Tofu"})
    assert response.status_code == 303
    (item,) = store.quick_items()
    assert (item.label, item.grams, item.food_id) == ("Tofu", 250, food.id)
    assert "Tofu" in writer.get("/quick").text
    writer.post(f"/quick/{item.id}/remove", data={})
    assert store.quick_items() == []


def test_quick_add_defaults_label_and_rejects_bad_input(writer, store, food):
    writer.post("/quick", data={"food_id": str(food.id), "grams": "100", "label": " "})
    assert store.quick_items()[0].label == "Tofu natur"
    assert writer.post("/quick", data={"food_id": str(food.id), "grams": "0"}).status_code == 400
    assert writer.post("/quick", data={"food_id": "999", "grams": "10"}).status_code == 404
    assert writer.post("/quick", data={"food_id": "x", "grams": "10"}).status_code == 400


def test_quick_log_and_undo(writer, store, food):
    item = store.add_quick_item(food.id, 250, "Tofu")
    response = writer.post(f"/quick/{item.id}/log", data={})
    assert response.status_code == 303
    (entry,) = store.entries_between(at(TODAY, 0), at(TODAY, 23, 59))
    assert (entry.origin, entry.source, entry.grams, entry.food_id) == (Origin.UI, Source.OFF, 250, food.id)
    assert entry.eaten_at.hour == 12
    assert entry.nutrients.protein_g == pytest.approx(27.5)

    page = writer.get(response.headers["location"]).text
    assert f"/entries/{entry.id}/undo" in page and "Rückgängig" in page
    assert writer.post(f"/entries/{entry.id}/undo", data={"next": "/"}).headers["location"] == "/"
    assert store.entries_between(at(TODAY, 0), at(TODAY, 23, 59)) == []
    assert "Rückgängig" not in writer.get(response.headers["location"]).text


def test_quick_buttons_on_today(client, store, food):
    store.add_quick_item(food.id, 250, "Tofu")
    page = client.get("/").text
    assert "+27,5&nbsp;g" in page and "/quick/1/log" in page
    assert 'aria-label="Tofu, 250 g, +27,5 g Protein, eintragen"' in page


def test_quick_log_unknown_item(writer):
    assert writer.post("/quick/5/log", data={}).status_code == 404


# Cross-site writes


@pytest.mark.parametrize(
    "path",
    ["/entries/1", "/entries/1/delete", "/entries/1/undo", "/quick", "/quick/1/remove", "/quick/1/log"],
)
def test_cross_site_post_is_rejected(store, seeded, path):
    client = TestClient(create_app(store), follow_redirects=False)
    body = {"amount": "1", "day": TODAY, "time": "08:00", "food_id": "1", "grams": "1"}
    attempts = ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"})
    for headers in attempts:
        assert client.post(path, data=body, headers=headers).status_code == 403, (path, headers)
    assert store.get_entry(1).grams == 250
    assert len(store.quick_items()) == 0


def test_cross_site_api_writes_are_rejected(store, seeded):
    client = TestClient(create_app(store))
    headers = {"Origin": "https://evil.example"}
    assert client.delete("/api/entries/1", headers=headers).status_code == 403
    assert client.patch("/api/entries/1", json={"grams": 1}, headers=headers).status_code == 403
    assert client.post("/api/quick", json={"food_id": 1, "grams": 1}, headers=headers).status_code == 403
    assert store.get_entry(1).grams == 250


def test_same_origin_signals_are_accepted(store, seeded):
    client = TestClient(create_app(store), follow_redirects=False)
    body = {"amount": "100", "day": TODAY, "time": "08:00"}
    assert client.post("/entries/1", data=body, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 303
    assert client.post("/entries/1", data=body, headers={"Origin": "http://testserver"}).status_code == 303
    forwarded = {"Origin": "https://snacky.example", "X-Forwarded-Host": "snacky.example"}
    assert client.post("/entries/1", data=body, headers=forwarded).status_code == 303


def test_reads_need_no_origin(client, seeded):
    assert client.get("/api/day").status_code == 200
    assert client.head("/").status_code == 200


# Week view


def test_week_view_without_opengym(client, seeded):
    page = client.get("/week").text
    assert "28.9. bis 4.10.2026" in page
    assert "Training" not in page and "openGym" not in page
    assert "Di, 29.9." in page and "52&nbsp;g" in page and "1.075&nbsp;kcal" in page
    assert 'class="tick"' in page  # the goal tick
    assert "/week?start=2026-09-21" in page
    assert "Im Schnitt 52 g Protein" in page


def test_week_view_with_start(client, seeded):
    page = client.get("/week?start=2026-09-21").text
    assert "21.9. bis 27.9.2026" in page and "/week?start=2026-09-28" in page
    assert client.get("/week?start=x").status_code == 400


def test_week_view_marks_training_days(store, seeded):
    gym = FakeGym([Workout(date(2026, 9, 29), "Session A", 50), Workout(date(2026, 10, 12), "Session B")])
    page = TestClient(create_app(store, opengym=gym)).get("/week").text
    assert page.count('class="tag-train"') == 1 and "Session A" in page
    assert "openGym" not in page
    assert gym.calls == [(date(2026, 9, 28), date(2026, 10, 5))]


@pytest.mark.parametrize("error", [OpenGymError("down"), RuntimeError("boom")])
def test_week_view_survives_opengym_failure(store, seeded, error):
    client = TestClient(create_app(store, opengym=FakeGym(error=error)))
    response = client.get("/week")
    assert response.status_code == 200
    assert "Trainingstage konnten nicht von openGym geladen werden" in response.text
    assert 'class="tag-train"' not in response.text and "52&nbsp;g" in response.text


def test_week_view_survives_opengym_timeout(store, seeded, monkeypatch):
    monkeypatch.setattr(web_app, "_OPENGYM_TIMEOUT_S", 0.01)

    class Slow:
        async def workouts_between(self, start, end):
            await asyncio.sleep(5)

    response = TestClient(create_app(store, opengym=Slow())).get("/week")
    assert response.status_code == 200 and "openGym" in response.text


# JSON API


def test_api_day(client, seeded):
    body = client.get(f"/api/day?day={TODAY}").json()
    assert body["day"] == TODAY
    assert body["totals"]["protein_g"] == pytest.approx(51.5)
    assert len(body["meals"]) == 2
    entry = body["meals"][0]["entries"][0]
    assert entry["source"] == "off" and entry["origin"] == "chat" and entry["nutrients"]["kcal"] == 375
    assert {g["goal"]["nutrient"] for g in body["goals"]} == {"protein_g", "kcal"}
    bad = client.get("/api/day?day=x")
    assert bad.status_code == 400 and "error" in bad.json()


def test_api_week(store, seeded):
    gym = FakeGym([Workout(date(2026, 9, 29), "Session A", 50)])
    body = TestClient(create_app(store, opengym=gym)).get("/api/week").json()
    assert body["start"] == "2026-09-28" and len(body["days"]) == 7
    assert body["training"] == [{"day": TODAY, "name": "Session A", "duration_min": 50}]
    assert body["training_available"] is True
    plain = TestClient(create_app(store)).get("/api/week").json()
    assert plain["training"] == [] and plain["training_available"] is False
    broken = TestClient(create_app(store, opengym=FakeGym(error=OpenGymError("x")))).get("/api/week")
    assert broken.status_code == 200 and broken.json()["training_available"] is False


def test_api_entry_update_and_delete(writer, store, seeded):
    response = writer.patch("/api/entries/1", json={"grams": 500, "eaten_at": f"{TODAY}T09:00:00"})
    assert response.status_code == 200
    assert response.json()["grams"] == 500 and response.json()["nutrients"]["protein_g"] == pytest.approx(55)
    assert store.get_entry(1).eaten_at.hour == 9
    assert writer.patch("/api/entries/1", json={"grams": -1}).status_code == 422
    assert writer.patch("/api/entries/1", json={"eaten_at": "soon"}).status_code == 422
    assert writer.patch("/api/entries/1", content="[]").status_code == 400
    assert writer.patch("/api/entries/99", json={"grams": 1}).status_code == 404
    assert writer.delete("/api/entries/1").json() == {"deleted": 1}
    assert writer.delete("/api/entries/1").status_code == 404


def test_api_quick_items(writer, store, food):
    created = writer.post("/api/quick", json={"food_id": food.id, "grams": 250, "label": "Tofu"})
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert writer.get("/api/quick").json()[0]["label"] == "Tofu"
    logged = writer.post(f"/api/quick/{item_id}/log")
    assert logged.status_code == 201 and logged.json()["origin"] == "ui"
    assert writer.post("/api/quick", json={"food_id": food.id, "grams": 0}).status_code == 422
    assert writer.post("/api/quick", json={"food_id": 99, "grams": 5}).status_code == 404
    assert writer.delete(f"/api/quick/{item_id}").status_code == 200
    assert writer.get("/api/quick").json() == []


def test_api_foods(client, food):
    (found,) = client.get("/api/foods?q=tofu").json()
    assert found["name"] == "Tofu natur" and found["servings"][0]["label"] == "1 Block"
    assert client.get("/api/foods").json() == []


def test_day_boundary_uses_local_time(client, store):
    store.log_entry(
        name="Late",
        nutrients=Nutrients(10, 1, 1, 1),
        eaten_at=datetime(2026, 9, 28, 23, 30, tzinfo=BERLIN),
        source=Source.MANUAL,
        origin=Origin.CHAT,
        grams=10,
    )
    assert "Late" in client.get("/?day=2026-09-28").text
    assert "Late" not in client.get("/").text
