"""The undo notice and its POST, driven through Starlette's TestClient."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

from snacky import config
from snacky.model import FoodCandidate, Nutrients, Origin, Source
from snacky.store import Store
from snacky.web import app as web_app
from snacky.web import create_app

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(config, "TZ", BERLIN)
    monkeypatch.setattr(web_app, "_now", lambda: NOW)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def writer(store):
    return TestClient(create_app(store), headers={"Origin": "http://testserver"}, follow_redirects=False)


def log(store, age_s: int, origin: Origin = Origin.UI):
    return store.log_entry(
        name="Linsensuppe",
        nutrients=Nutrients(300, 18, 4, 40),
        eaten_at=NOW - timedelta(seconds=age_s),
        source=Source.MANUAL,
        origin=origin,
        grams=400,
    )


@pytest.mark.parametrize("path", ["/", "/quick"])
def test_undo_shown_for_a_fresh_ui_entry(writer, store, path):
    entry = log(store, 119)
    assert f"/entries/{entry.id}/undo" in writer.get(f"{path}?undo={entry.id}").text


@pytest.mark.parametrize("age", [120, 121, 3600])
def test_undo_ignored_when_stale(writer, store, age):
    entry = log(store, age)
    assert "Rückgängig" not in writer.get(f"/?undo={entry.id}").text


def test_undo_ignored_for_chat_origin(writer, store):
    entry = log(store, 5, Origin.CHAT)
    assert "Rückgängig" not in writer.get(f"/?undo={entry.id}").text


def test_undo_ignored_for_a_future_entry(writer, store):
    entry = log(store, -300)
    assert "Rückgängig" not in writer.get(f"/?undo={entry.id}").text


@pytest.mark.parametrize("value", ["999", "abc", "", "-1", "1.5"])
def test_undo_ignored_for_unknown_or_bad_ids(writer, store, value):
    log(store, 5)
    assert writer.get(f"/?undo={value}").status_code == 200
    assert "Rückgängig" not in writer.get(f"/?undo={value}").text


def test_undo_post_deletes_a_fresh_entry(writer, store):
    entry = log(store, 119)
    response = writer.post(f"/entries/{entry.id}/undo", data={"next": "/quick"})
    assert response.status_code == 303 and response.headers["location"] == "/quick"
    assert store.entries_between(NOW - timedelta(days=1), NOW + timedelta(days=1)) == []


@pytest.mark.parametrize(("age", "origin"), [(121, Origin.UI), (5, Origin.CHAT), (5, Origin.TANDOOR)])
def test_undo_post_rejects_what_the_notice_would_hide(writer, store, age, origin):
    entry = log(store, age, origin)
    response = writer.post(f"/entries/{entry.id}/undo", data={})
    assert response.status_code == 409
    assert "Rückgängig geht nur kurz nach dem Eintragen" in response.text
    assert store.get_entry(entry.id).name == "Linsensuppe"


def test_undo_post_of_a_missing_entry_is_404(writer):
    assert writer.post("/entries/999/undo", data={}).status_code == 404


def test_quick_log_returns_to_the_page_it_came_from(writer, store):
    food = store.upsert_food(
        FoodCandidate(name="Kichererbsen", source=Source.MANUAL, per_100g=Nutrients(120, 8, 2, 18, 5))
    )
    item = store.add_quick_item(food.id, 200, "Kichererbsen")
    from_quick = writer.post(f"/quick/{item.id}/log", data={"next": "/quick"})
    assert from_quick.headers["location"].startswith("/quick?undo=")
    assert "Rückgängig" in writer.get(from_quick.headers["location"]).text
    # Anything but the two pages that show the notice falls back to the day page.
    for nxt in ("https://example.org/", "//example.org", "/week", ""):
        assert (
            writer.post(f"/quick/{item.id}/log", data={"next": nxt}).headers["location"].startswith("/?undo=")
        )
    assert writer.post(f"/quick/{item.id}/log", data={}).headers["location"].startswith("/?undo=")


def test_app_js_strips_undo_from_the_url(writer):
    js = writer.get("/static/app.js").text
    assert "replaceState" in js and 'delete("undo")' in js
