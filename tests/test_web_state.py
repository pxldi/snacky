"""The state the day, week and quick pages hand to their templates.
Test data is made up and plant-based; the goals are generic."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import jinja2
import pytest
from starlette.testclient import TestClient

from snacky import config
from snacky.model import (
    Confidence,
    Entry,
    FoodCandidate,
    Goal,
    GoalKind,
    GoalStatus,
    Nutrients,
    Origin,
    Source,
)
from snacky.store import Store
from snacky.web import app as web_app
from snacky.web import create_app
from snacky.web import format as fmt

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)  # a Tuesday
TODAY = date(2026, 9, 29)
GOAL = 100.0


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(config, "TZ", BERLIN)
    monkeypatch.setattr(config, "MEAL_GAP", timedelta(minutes=90))
    monkeypatch.setattr(web_app, "_now", lambda: NOW)
    monkeypatch.delenv("SNACKY_MEAL_PROTEIN_MIN", raising=False)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 1, 1), min=GOAL))
    yield s
    s.close()


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


@pytest.fixture
def contexts(monkeypatch):
    """Every template render as (template name, context), newest last."""
    seen = []
    original = jinja2.Template.render

    def spy(self, *args, **kwargs):
        seen.append((self.name, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(jinja2.Template, "render", spy)
    return seen


def eat(store, day: date, protein: float, hour: int = 12, **kwargs):
    fields = {"source": Source.MANUAL, "origin": Origin.CHAT, "grams": 100}
    fields.update(kwargs)
    return store.log_entry(
        name="Seitan",
        nutrients=Nutrients(protein * 4, protein, 1, 1),
        eaten_at=datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN),
        **fields,
    )


def day_context(client, contexts, day: str | None = None):
    contexts.clear()
    url = "/" if day is None else f"/?day={day}"
    assert client.get(url).status_code == 200
    return next(ctx for name, ctx in contexts if name == "day.html")


def entry(**kwargs) -> Entry:
    fields = {
        "id": 1,
        "eaten_at": NOW,
        "name": "Tempeh",
        "nutrients": Nutrients(200, 18.4, 8, 5),
        "source": Source.MANUAL,
        "origin": Origin.CHAT,
        "grams": 150,
    }
    fields.update(kwargs)
    return Entry(**fields)


# CSP


def test_csp_allows_self_hosted_fonts_and_stays_strict(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "font-src 'self'" in csp
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "style-src 'self'" in csp


# Protein state per day


@pytest.mark.parametrize(
    ("day", "protein", "state"),
    [
        ("2026-09-29", None, "empty"),  # today, nothing logged
        ("2026-09-29", 40, "open"),
        ("2026-09-29", 100, "met"),
        ("2026-09-15", 40, "missed"),  # past, no DST change nearby
        ("2026-09-15", 130, "met"),
        ("2026-09-15", None, "empty"),
        ("2026-10-02", None, "empty"),  # future
    ],
)
def test_protein_state(client, store, contexts, day, protein, state):
    if protein is not None:
        eat(store, date.fromisoformat(day), protein)
    view = day_context(client, contexts, day)["protein"]
    assert view["state"] == state
    assert view["met"] is (state == "met")


def test_future_day_with_entries_is_open(client, store, contexts):
    eat(store, date(2026, 10, 2), 30)
    assert day_context(client, contexts, "2026-10-02")["protein"]["state"] == "open"


def test_protein_numbers(client, store, contexts):
    eat(store, TODAY, 40)
    view = day_context(client, contexts)["protein"]
    assert (view["eaten"], view["limit"], view["gap"], view["over"], view["fraction"]) == (
        40,
        100,
        60,
        0,
        0.4,
    )
    eat(store, TODAY, 85, hour=8)
    view = day_context(client, contexts)["protein"]
    assert (view["gap"], view["over"], view["fraction"]) == (0, 25, 1.0)


def test_protein_without_a_goal(contexts, monkeypatch):
    s = Store(":memory:")
    eat(s, TODAY, 40)
    view = day_context(TestClient(create_app(s)), contexts)["protein"]
    assert view["state"] == "nogoal" and view["limit"] is None
    assert (view["gap"], view["over"], view["fraction"], view["met"]) == (0, 0, 0, False)


def test_protein_view_keeps_the_keys_templates_use():
    status = GoalStatus(Goal("protein_g", GoalKind.MIN, date(2026, 1, 1), min=100), 40, False)
    view = fmt.protein_view(status, day=TODAY, today=TODAY, has_entries=True)
    assert {"target", "short", "gap_text", "met", "fill", "limit"} <= view.keys()
    assert view["gap_text"] == "noch 60 g"


def test_api_day_carries_the_protein_state(client, store):
    eat(store, TODAY, 40, source=Source.AI_ESTIMATE)
    body = client.get("/api/day").json()
    assert body["protein"]["state"] == "open" and body["protein"]["gap"] == 60
    assert body["protein_estimated_share"] == 1.0
    assert "totals" in body and "meals" in body  # the old shape is intact


# Protein estimate share


def test_protein_estimated_share(client, store, contexts):
    eat(store, TODAY, 30, hour=8)
    eat(store, TODAY, 10, hour=12, source=Source.AI_ESTIMATE)
    eat(store, TODAY, 10, hour=18, source=Source.LABEL, confidence=Confidence.MEDIUM)
    eat(store, TODAY, 50, hour=21, source=Source.LABEL, confidence=Confidence.HIGH)
    assert day_context(client, contexts)["protein_estimated_share"] == pytest.approx(0.2)


def test_protein_estimated_share_is_zero_without_protein(client, store, contexts):
    assert day_context(client, contexts)["protein_estimated_share"] == 0.0
    eat(store, TODAY, 0, source=Source.AI_ESTIMATE)
    assert day_context(client, contexts)["protein_estimated_share"] == 0.0


# Gap closer


def add_quick(store, protein: float) -> None:
    food = store.upsert_food(
        FoodCandidate(
            name=f"Riegel {protein:g}",
            source=Source.MANUAL,
            per_100g=Nutrients(protein * 4, protein, 1, 1),
            source_ref=f"riegel-{protein:g}",
        )
    )
    store.add_quick_item(food.id, 100, f"Riegel {protein:g}")


def marked(ctx) -> list[str]:
    assert [q["closes_gap"] for q in ctx["quick"]].count(True) <= 1
    return [q["item"].label for q in ctx["quick"] if q["closes_gap"]]


def test_gap_closer_picks_the_smallest_item_that_reaches_the_gap(client, store, contexts):
    for protein in (10, 25, 60, 40):
        add_quick(store, protein)
    eat(store, TODAY, 60)  # gap 40
    assert marked(day_context(client, contexts)) == ["Riegel 40"]  # exact reach counts


def test_gap_closer_between_two_items(client, store, contexts):
    for protein in (10, 25, 60):
        add_quick(store, protein)
    eat(store, TODAY, 70)  # gap 30
    assert marked(day_context(client, contexts)) == ["Riegel 60"]


def test_gap_closer_falls_back_to_the_largest_item(client, store, contexts):
    for protein in (10, 25, 15):
        add_quick(store, protein)
    eat(store, TODAY, 20)  # gap 80, nothing reaches it
    assert marked(day_context(client, contexts)) == ["Riegel 25"]


@pytest.mark.parametrize(("logged", "day"), [(None, None), (120, None), (40, "2026-09-15")])
def test_gap_closer_marks_nothing_unless_the_day_is_open(client, store, contexts, logged, day):
    add_quick(store, 25)
    if logged is not None:
        eat(store, date.fromisoformat(day) if day else TODAY, logged)
    ctx = day_context(client, contexts, day)
    assert marked(ctx) == []


def test_gap_closer_marks_nothing_without_a_goal(contexts):
    s = Store(":memory:")
    add_quick(s, 25)
    eat(s, TODAY, 10)
    assert marked(day_context(TestClient(create_app(s)), contexts)) == []


# Navigation state


def test_nav_current_per_page(client, store, contexts):
    def nav(path):
        contexts.clear()
        client.get(path)
        return contexts[0][1]["nav_current"]

    eat(store, TODAY, 10)
    assert nav("/") == "day"
    assert nav("/?day=2026-09-28") is None
    assert nav("/?day=2026-09-30") is None
    assert nav("/week") == "week"
    assert nav("/quick") == "quick"
    assert nav("/entries/1") is None
    assert nav("/entries/1/delete") is None
    assert nav("/nowhere") is None


def test_nav_marks_the_current_link_only(client):
    def current(path):
        return re.findall(r'<a href="([^"]+)" aria-current="page"', client.get(path).text)

    assert current("/") == ["/"]
    assert current("/?day=2026-09-28") == []
    assert current("/week") == ["/week"]
    assert current("/quick") == ["/quick"]


@pytest.mark.parametrize(
    ("day", "today", "past"),
    [("2026-09-29", True, False), ("2026-09-28", False, True), ("2026-09-30", False, False)],
)
def test_is_today_and_is_past(client, contexts, day, today, past):
    ctx = day_context(client, contexts, day)
    assert (ctx["is_today"], ctx["is_past"]) == (today, past)


# Labels


@pytest.mark.parametrize(
    ("grams", "servings", "label"),
    [
        (150, None, "150 g"),
        (37.5, None, "37,5 g"),
        (None, 1, "1 Portion"),
        (None, 2.5, "2,5 Portionen"),
        (None, 2, "2 Portionen"),
        (None, 0.5, "0,5 Portionen"),
    ],
)
def test_amount_label(grams, servings, label):
    assert fmt.amount_label(entry(grams=grams, servings=servings)) == label


def test_missing_values_say_so():
    assert fmt.value_label(None, "g", 1) == "keine Angabe"
    assert fmt.value_label(0, "g", 1) == "0,0 g"
    assert fmt.value_label(4.26, "g", 1) == "4,3 g"


def test_edit_page_says_when_fibre_is_missing(client, store):
    eat(store, TODAY, 10)
    page = client.get("/entries/1").text
    assert "keine Angabe" in page and "– g" not in page


def test_protein_label_rounds_estimates_to_whole_grams():
    assert fmt.protein_label(entry()) == "18,4 g"
    guess = entry(source=Source.AI_ESTIMATE)
    assert fmt.protein_label(guess) == "≈ 18 g"
    assert fmt.protein_label(entry(confidence=Confidence.LOW)) == "≈ 18 g"
    assert fmt.protein_label(entry(confidence=Confidence.HIGH)) == "18,4 g"
    assert fmt.protein_label(entry(source=Source.AI_ESTIMATE, nutrients=Nutrients(0, 24.5, 0, 0))) == "≈ 25 g"


# Week view


def week_context(client, contexts, start: str | None = None):
    contexts.clear()
    assert client.get("/week" if start is None else f"/week?start={start}").status_code == 200
    return next(ctx for name, ctx in contexts if name == "week.html")


def test_week_row_states_in_the_current_week(client, store, contexts):
    eat(store, date(2026, 9, 28), 120)  # Monday, met
    ctx = week_context(client, contexts)
    states = [r["state"] for r in ctx["rows"]]
    assert states == ["met", "today", "future", "future", "future", "future", "future"]
    assert (ctx["met_count"], ctx["counted_days"], ctx["has_goal"]) == (1, 2, True)


def test_week_today_counts_when_met(client, store, contexts):
    eat(store, date(2026, 9, 28), 40)
    eat(store, TODAY, 100)
    ctx = week_context(client, contexts)
    assert [r["state"] for r in ctx["rows"]][:2] == ["missed", "today"]
    assert (ctx["met_count"], ctx["counted_days"]) == (1, 2)


def test_week_past_week(client, store, contexts):
    eat(store, date(2026, 9, 21), 100)  # met
    eat(store, date(2026, 9, 22), 60)  # missed
    eat(store, date(2026, 9, 24), 130)  # met
    ctx = week_context(client, contexts, "2026-09-21")
    assert [r["state"] for r in ctx["rows"]] == ["met", "missed", "empty", "met", "empty", "empty", "empty"]
    assert (ctx["met_count"], ctx["counted_days"]) == (2, 7)


def test_week_future_week(client, contexts):
    ctx = week_context(client, contexts, "2026-10-05")
    assert {r["state"] for r in ctx["rows"]} == {"future"}
    assert (ctx["met_count"], ctx["counted_days"], ctx["average"]) == (0, 0, None)


def test_week_row_numbers(client, store, contexts):
    eat(store, date(2026, 9, 28), 50, hour=9)
    row = week_context(client, contexts)["rows"][0]
    assert (row["protein"], row["goal"], row["fraction"]) == (50, 100, 0.5)
    assert row["kcal"] == 200 and row["training"] == []
    eat(store, date(2026, 9, 28), 100, hour=18)
    assert week_context(client, contexts)["rows"][0]["fraction"] == 1.0


def test_week_without_a_goal(contexts):
    s = Store(":memory:")
    eat(s, date(2026, 9, 28), 50)
    ctx = week_context(TestClient(create_app(s)), contexts)
    assert ctx["has_goal"] is False
    assert ctx["rows"][0]["fraction"] is None and ctx["rows"][0]["goal"] is None
    assert ctx["rows"][0]["state"] == "logged" and ctx["met_count"] == 0


def test_week_average_is_over_days_with_entries(client, store, contexts):
    eat(store, date(2026, 9, 28), 50)
    eat(store, TODAY, 100)
    assert week_context(client, contexts)["average"] == 75


# Quick page


def test_quick_page_context(client, store, contexts):
    add_quick(store, 25)
    contexts.clear()
    client.get("/quick")
    ctx = next(c for name, c in contexts if name == "quick.html")
    assert ctx["nav_current"] == "quick" and ctx["undo"] is None
    assert len(ctx["items"]) == 1
