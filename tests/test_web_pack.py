"""The pack markup: stickers, coupons, the label table and the CSP rules.
Test data is made up and plant-based; the goal is a generic 100 g."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

from snacky import config
from snacky.model import Confidence, FoodCandidate, Goal, GoalKind, Nutrients, Origin, Source
from snacky.store import Store
from snacky.web import app as web_app
from snacky.web import create_app

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)
TODAY = date(2026, 9, 29)
PAST = date(2026, 9, 15)


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(config, "TZ", BERLIN)
    monkeypatch.setattr(config, "MEAL_GAP", timedelta(minutes=90))
    monkeypatch.setattr(web_app, "_now", lambda: NOW)
    monkeypatch.delenv("SNACKY_MEAL_PROTEIN_MIN", raising=False)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 1, 1), min=100))
    s.set_goal(Goal("kcal", GoalKind.BAND, date(2026, 1, 1), min=2200, max=2600))
    yield s
    s.close()


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def eat(store, day: date, protein: float, hour: int = 12, **kwargs):
    fields = {"source": Source.MANUAL, "origin": Origin.CHAT, "grams": 100}
    fields.update(kwargs)
    return store.log_entry(
        name=kwargs.pop("name", "Seitan"),
        nutrients=Nutrients(protein * 4, protein, 1, 1, 2),
        eaten_at=datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN),
        **fields,
    )


def sticker(client, day: date) -> str:
    page = client.get(f"/?day={day.isoformat()}").text
    found = re.search(r'<div class="sticker[^"]*">(.*?)</div>', page, re.S)
    return re.sub(r"<[^>]+>|&nbsp;", " ", found.group(1)) if found else ""


def words(text: str) -> list[str]:
    return text.split()


def test_sticker_open_names_the_gap(client, store):
    eat(store, TODAY, 60)
    assert words(sticker(client, TODAY)) == ["Noch", "40", "g"]


def test_sticker_met_says_geschafft_and_the_surplus(client, store):
    eat(store, TODAY, 100)
    assert words(sticker(client, TODAY)) == ["Geschafft!"]
    eat(store, TODAY, 12, hour=9)
    assert words(sticker(client, TODAY)) == ["Geschafft!", "+12", "g"]


def test_sticker_missed_past_day_is_information(client, store):
    eat(store, PAST, 70)
    assert words(sticker(client, PAST)) == ["30", "g", "Unter", "Ziel"]


def test_sticker_empty_today_only(client):
    assert words(sticker(client, TODAY)) == ["Los", "geht's"]
    assert sticker(client, PAST) == ""


def test_no_sticker_without_a_goal():
    s = Store(":memory:")
    try:
        eat(s, TODAY, 40)
        page = TestClient(create_app(s)).get("/").text
        assert 'class="sticker' not in page and "Kein Proteinziel gesetzt." in page
    finally:
        s.close()


def test_fill_is_drawn_with_svg_attributes(client, store):
    eat(store, TODAY, 25)
    page = client.get("/").text
    assert '<path class="fill" d="M0 75.0 q8.333 -2.4 16.667 0' in page
    # The cap names the share, so the level can be read without the colours.
    assert "100&nbsp;g · 25&nbsp;%" in page


def test_met_day_fills_the_whole_front(client, store):
    eat(store, TODAY, 130)
    page = client.get("/").text
    assert 'data-state="met"' in page
    assert '<rect class="fill" x="0" y="0" width="100" height="100"/>' in page


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


def test_coupon_names_the_verb_and_flags_the_gap_closer(client, store):
    eat(store, TODAY, 70)
    for protein in (10, 30, 50):
        add_quick(store, protein)
    page = client.get("/").text
    assert 'aria-label="Riegel 10, 100 g, +10 g Protein, eintragen"' in page
    assert 'aria-label="Riegel 30, 100 g, +30 g Protein, eintragen, schließt die Lücke"' in page
    assert page.count("schließt die Lücke</span>") == 1
    assert "+30&nbsp;g" in page


def test_no_coupons_on_a_past_day(client, store):
    add_quick(store, 30)
    assert 'class="coupon' not in client.get(f"/?day={PAST.isoformat()}").text


def test_coupon_hint_links_to_quick_when_there_are_none(client):
    assert 'href="/quick">Lege welche an.' in client.get("/").text


def test_edit_page_follows_the_legal_nutrient_order(client, store):
    eat(store, TODAY, 20)
    page = client.get("/entries/1").text
    order = ["Energie", "Fett", "Kohlenhydrate", "Ballaststoffe", "Eiweiß"]
    positions = [page.index(f'<th scope="row">{label}</th>') for label in order]
    assert positions == sorted(positions)
    assert 'class="nutri-protein"' in page


def test_edit_page_explains_estimates(client, store):
    eat(store, TODAY, 20, source=Source.AI_ESTIMATE, confidence=Confidence.LOW, servings=1, grams=None)
    page = client.get("/entries/1").text
    assert "Schätzung:" in page and "nicht aus einer Datenbank" in page
    assert "≈ 20 g" in page


def test_delete_page_offers_the_safe_action_first(client, store):
    eat(store, TODAY, 20)
    page = client.get("/entries/1/delete").text
    assert page.index("Abbrechen") < page.index("Ja, löschen")
    assert re.search(r'class="btn btn-primary" href="/entries/1">Abbrechen', page)
    assert 'class="btn btn-danger">Ja, löschen' in page


def test_quick_page_removal_needs_a_second_step_without_script(client, store):
    add_quick(store, 30)
    page = client.get("/quick").text
    assert "<details" in page and "Wirklich entfernen" in page
    assert 'action="/quick/1/log"' in page and 'name="next" value="/quick"' in page


def test_quick_search_previews_the_default_amount(client, store):
    add_quick(store, 30)
    page = client.get("/quick?q=riegel").text
    assert "data-out-protein" in page and "Pro 100 g" in page.replace("&nbsp;", " ")


def test_undo_notice_is_a_status(client, store):
    entry = eat(store, TODAY, 20, origin=Origin.UI)
    page = client.get(f"/?undo={entry.id}").text
    assert 'role="status"' in page and "Eingetragen: Seitan" in page


def test_week_headline_and_row_states(client, store):
    eat(store, TODAY - timedelta(days=1), 120)  # Monday, met
    eat(store, TODAY, 40)  # today, open
    page = client.get("/week").text
    # Monday counts, today does not until it is met.
    assert 'claim-num">1<span class="claim-of">von</span>1' in page and "Tagen dabei" in page
    assert "Ø 120 von 100&nbsp;g Protein" in page
    assert "geschafft</span>" in page and "Heute</span>" in page
    assert '<span class="w-num">40</span><span class="w-of"> von 100</span>&nbsp;g' in page
    assert 'aria-label="Mo, 28.9., 120 von 100 g, geschafft"' in page
    assert "darunter" not in page
    assert '<span class="w-protein">–</span>' in page  # future days


def test_future_week_says_it_has_not_started(client):
    assert "Woche noch nicht angefangen" in client.get("/week?start=2026-10-05").text


def test_main_navigation_marks_the_current_page_twice(client):
    page = client.get("/week").text
    assert 'href="/week" aria-current="page"' in page


def test_heading_comes_before_day_navigation(client, store):
    eat(store, TODAY, 20)
    page = client.get("/").text
    assert page.index("<h1") < page.index('aria-label="Tag wechseln"')


ERROR_PAGES = ["/entries/999", "/nowhere", "/?day=nonsense"]


def test_no_page_carries_inline_style_or_script(store):
    eat(store, TODAY, 130)
    eat(store, TODAY, 20, hour=8, source=Source.AI_ESTIMATE, confidence=Confidence.LOW)
    eat(store, PAST, 40)
    add_quick(store, 30)
    client = TestClient(create_app(store))
    paths = [
        "/",
        f"/?day={PAST.isoformat()}",
        "/?day=2026-09-01",
        "/week",
        "/week?start=2026-10-05",
        "/quick",
        "/quick?q=riegel",
        "/quick?q=zzzz",
        "/entries/1",
        "/entries/1/delete",
        *ERROR_PAGES,
    ]
    for path in paths:
        page = client.get(path).text
        assert not re.search(r"\sstyle\s*=", page, re.I) and "<style" not in page, path
        assert not re.search(r"<script(?![^>]*\bsrc=)", page), path
        assert not re.search(r"\son[a-z]+\s*=", page, re.I), path
    bad = TestClient(create_app(store), headers={"Origin": "http://testserver"}).post(
        "/entries/1", data={"amount": "x", "day": TODAY.isoformat(), "time": "08:00"}
    )
    assert bad.status_code == 400 and "style=" not in bad.text


def test_edit_page_shows_two_columns_when_the_entry_has_a_food(client, store):
    food = store.upsert_food(
        FoodCandidate(
            name="Tofu natur",
            source=Source.OFF,
            per_100g=Nutrients(150, 11, 7, 1, None),
            source_ref="tofu-1",
        )
    )
    store.log_entry(
        name=food.name,
        nutrients=food.per_100g.for_grams(200),
        eaten_at=NOW,
        source=Source.OFF,
        origin=Origin.CHAT,
        grams=200,
        food_id=food.id,
    )
    page = client.get("/entries/1").text
    assert "je 100&nbsp;g" in page and "diese Portion" in page
    assert "<td>11,0&nbsp;g</td>" in page and "22,0" in page
    assert page.count("keine Angabe") == 2


def test_edit_page_keeps_one_column_without_a_food(client, store):
    eat(store, TODAY, 20)
    page = client.get("/entries/1").text
    assert "je 100" not in page and "diese Portion" not in page


def test_units_are_not_upper_cased(client):
    css = client.get("/static/app.css").text
    for selector in (".row-meta", ".coupon-amount", ".mtag"):
        block = css[css.index(selector + " {") :].split("}")[0]
        assert "text-transform" not in block, selector


def week_hero(client, contexts, start=None):
    contexts.clear()
    client.get("/week" if start is None else f"/week?start={start}")
    return next(ctx for name, ctx in contexts if name == "week.html")["hero"]


@pytest.fixture
def contexts(monkeypatch):
    import jinja2

    seen = []
    original = jinja2.Template.render

    def spy(self, *args, **kwargs):
        seen.append((self.name, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(jinja2.Template, "render", spy)
    return seen


def test_hero_current_week_leaves_out_an_unmet_today(client, store, contexts):
    eat(store, date(2026, 9, 28), 60)
    eat(store, TODAY, 90)
    hero = week_hero(client, contexts)
    assert (hero["days"], hero["logged"], hero["fraction"], hero["average"], hero["goal"]) == (
        1,
        1,
        0.6,
        60,
        100,
    )


def test_hero_counts_today_once_it_is_met(client, store, contexts):
    eat(store, date(2026, 9, 28), 60)
    eat(store, TODAY, 100)
    hero = week_hero(client, contexts)
    assert (hero["days"], hero["logged"], hero["fraction"], hero["average"]) == (2, 2, 0.8, 80)


def test_hero_past_week_counts_empty_days_in_the_fill_but_not_the_average(client, store, contexts):
    eat(store, date(2026, 9, 21), 100)
    eat(store, date(2026, 9, 22), 50)
    hero = week_hero(client, contexts, "2026-09-21")
    assert (hero["days"], hero["logged"], hero["average"]) == (7, 2, 75)
    assert hero["fraction"] == pytest.approx(150 / 700)


def test_hero_future_week_is_empty(client, contexts):
    hero = week_hero(client, contexts, "2026-10-05")
    assert (hero["days"], hero["logged"], hero["fraction"], hero["average"], hero["goal"]) == (
        0,
        0,
        0.0,
        None,
        None,
    )
    assert "Woche noch nicht angefangen" in client.get("/week?start=2026-10-05").text


def test_hero_without_goals_shows_days_and_average_only(contexts):
    s = Store(":memory:")
    try:
        eat(s, date(2026, 9, 28), 50)
        client = TestClient(create_app(s))
        hero = week_hero(client, contexts)
        assert (hero["days"], hero["logged"], hero["fraction"], hero["average"], hero["goal"]) == (
            1,
            1,
            0.0,
            50,
            None,
        )
        page = client.get("/week").text
        assert "Ø 50&nbsp;g Protein" in page and " von 100" not in page
    finally:
        s.close()


def test_week_rows_carry_one_clean_name(client, store):
    eat(store, date(2026, 9, 28), 154)
    page = client.get("/week").text
    assert 'aria-label="Mo, 28.9., 154 von 100 g, geschafft"' in page
    assert 'role="img"' not in page


def test_skip_link_comes_first(client):
    page = client.get("/").text
    assert page.index('class="skip"') < page.index("<header") and 'id="main"' in page


def test_undo_sets_the_title_and_the_fill_start(writer_client, store):
    eat(store, TODAY, 60)
    entry = eat(store, TODAY, 20, hour=12, origin=Origin.UI)
    page = writer_client.get(f"/?undo={entry.id}").text
    assert "<title>Eingetragen: Seitan · Snacky</title>" in page
    assert 'data-from="0.750"' in page  # 60 of 80 g before this entry
    assert "data-from" not in writer_client.get("/").text


@pytest.fixture
def writer_client(store):
    return TestClient(create_app(store), headers={"Origin": "http://testserver"})


def test_past_front_names_the_day_in_its_cap(client, store):
    eat(store, PAST, 70)
    page = client.get(f"/?day={PAST.isoformat()}").text
    assert "front-past" in page and "Di 15.9. · Ziel</span> 100&nbsp;g" in page
    assert "front-past" not in client.get("/").text


def test_missed_day_says_the_same_in_sticker_and_total(client, store):
    eat(store, PAST, 93)
    page = client.get(f"/?day={PAST.isoformat()}").text
    assert page.count("7&nbsp;g unter Ziel") == 1 and "Unter Ziel" in page  # total; sticker splits the words
    assert "Noch 7" not in page


def test_entry_rows_have_a_chevron(client, store):
    eat(store, TODAY, 20)
    row = client.get("/").text.split('class="row"')[1].split("</a>")[0]
    assert 'class="icon"' in row


def test_estimate_confidence_wording(client, store):
    eat(store, TODAY, 20, source=Source.AI_ESTIMATE, confidence=Confidence.LOW, servings=1, grams=None)
    eat(store, TODAY, 20, hour=8, source=Source.LABEL, confidence=Confidence.MEDIUM)
    page = client.get("/").text
    assert "geschätzt, unsicher" in page and "geschätzt, eher sicher" in page
    assert "(niedrig)" not in page


class FakeGym:
    def __init__(self, workouts=None, error=None):
        self.workouts, self.error = workouts or [], error

    async def workouts_between(self, start, end):
        if self.error:
            raise self.error
        return [w for w in self.workouts if start <= w.day < end]


def test_day_front_shows_a_training_tag(store):
    from snacky.model import Workout

    gym = FakeGym([Workout(TODAY, "Session A", 50)])
    page = TestClient(create_app(store, opengym=gym)).get("/").text
    assert 'class="tag-train">Training</span> Session A' in page
    assert 'class="tag-train"' not in TestClient(create_app(store, opengym=FakeGym())).get("/").text


@pytest.mark.parametrize("error", [RuntimeError("boom"), TimeoutError()])
def test_day_page_renders_when_opengym_fails(store, error):
    response = TestClient(create_app(store, opengym=FakeGym(error=error))).get("/")
    assert response.status_code == 200 and "tag-train" not in response.text


def test_day_page_without_opengym_has_no_tag(client):
    assert "tag-train" not in client.get("/").text


def test_stylesheet_uses_only_the_declared_type_sizes(client):
    css = client.get("/static/app.css").text
    body = css.split("--heavy", 1)[1]
    assert not re.findall(r"font(?:-size)?:[^;]*?\d(?:\.\d+)?rem", body)
