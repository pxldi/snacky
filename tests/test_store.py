import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

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
)
from snacky.store import DuplicateEntry, NotFound, Store

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture(autouse=True)
def berlin(monkeypatch):
    monkeypatch.setattr(config, "TZ", BERLIN)
    monkeypatch.setattr(config, "MEAL_GAP", timedelta(minutes=90))


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def at(day: str, hh: int, mm: int = 0, fold: int = 0) -> datetime:
    y, m, d = (int(p) for p in day.split("-"))
    return datetime(y, m, d, hh, mm, tzinfo=BERLIN, fold=fold)


def n(kcal=100.0, protein=10.0, fat=1.0, carbs=5.0, fibre=None) -> Nutrients:
    return Nutrients(kcal, protein, fat, carbs, fibre)


def food(name="Oat Flakes", ref="x1", brand=None, source=Source.MANUAL, **kw) -> FoodCandidate:
    return FoodCandidate(
        name=name, source=source, per_100g=n(370, 13, 7, 60, 10), source_ref=ref, brand=brand, **kw
    )


def log(store, when, kcal=100.0, protein=10.0, source=Source.MANUAL, **kw):
    return store.log_entry(
        name=kw.pop("name", "Test item"),
        nutrients=n(kcal, protein),
        eaten_at=when,
        source=source,
        origin=Origin.CHAT,
        **kw,
    )


# Foods


def test_migrate_is_idempotent(store):
    store.migrate()
    store.migrate()
    assert store._db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_upsert_and_get_food(store):
    created = store.upsert_food(food(brand="Acme", servings=(Serving("1 bowl", 40),), extra={"B1": 0.5}))
    assert store.get_food(created.id) == created
    assert created.per_100g == n(370, 13, 7, 60, 10)
    assert created.servings == (Serving("1 bowl", 40),)
    assert created.extra == {"B1": 0.5}


def test_upsert_keeps_id_and_updates(store):
    first = store.upsert_food(food(servings=(Serving("1 bowl", 40),)))
    second = store.upsert_food(
        FoodCandidate(
            name="Oat Flakes Fine",
            source=Source.MANUAL,
            per_100g=n(380, 14, 7, 60),
            source_ref="x1",
            servings=(Serving("1 bowl", 45),),
        )
    )
    assert second.id == first.id
    assert second.name == "Oat Flakes Fine"
    assert second.per_100g.kcal == 380
    assert second.servings == (Serving("1 bowl", 45),)
    assert [f.id for f in store.search_foods("oat")] == [first.id]


def test_same_ref_in_other_source_is_a_new_food(store):
    a = store.upsert_food(food(ref="42", source=Source.BLS))
    b = store.upsert_food(food(ref="42", source=Source.OFF))
    assert a.id != b.id


def test_no_source_ref_always_inserts(store):
    a = store.upsert_food(food(ref=None))
    b = store.upsert_food(food(ref=None))
    assert a.id != b.id


def test_get_food_not_found(store):
    with pytest.raises(NotFound):
        store.get_food(999)


def test_failed_upsert_leaves_nothing_behind(store):
    bad = food("Oat Flakes", "r1", servings=(Serving("ok", 10), Serving("bad", None)))  # type: ignore[arg-type]
    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_food(bad)
    assert store.search_foods("oat") == []
    assert store._db.execute("SELECT count(*) FROM foods").fetchone()[0] == 0
    assert store._db.execute("SELECT count(*) FROM servings").fetchone()[0] == 0
    store.upsert_food(food("Oat Flakes", "r1"))  # the lock and the connection still work
    assert len(store.search_foods("oat")) == 1


def test_search_index_follows_update_and_delete(store):
    f = store.upsert_food(food("Oat Flakes", "r1", brand="Acme"))
    store.upsert_food(food("Barley Groats", "r1", brand="Zeta"))
    assert store.search_foods("oat") == []
    assert store.search_foods("acme") == []
    assert [x.id for x in store.search_foods("zeta")] == [f.id]
    store._db.execute("DELETE FROM foods WHERE id = ?", (f.id,))
    assert store.search_foods("barley") == []
    store._db.execute("INSERT INTO foods_fts (foods_fts) VALUES ('integrity-check')")


def test_food_by_source_ref(store):
    oat = store.upsert_food(food("Oat Flakes", ref="1001", source=Source.OFF))
    store.add_serving(oat.id, Serving("1 Cup", 80))
    found = store.food_by_source_ref(Source.OFF, "1001")
    assert found == store.get_food(oat.id)
    assert found.servings == (Serving("1 Cup", 80),)


def test_food_by_source_ref_needs_both_parts(store):
    store.upsert_food(food("Oat Flakes", ref="1001", source=Source.OFF))
    assert store.food_by_source_ref(Source.LABEL, "1001") is None
    assert store.food_by_source_ref(Source.OFF, "1002") is None


def test_add_serving(store):
    f = store.upsert_food(food())
    updated = store.add_serving(f.id, Serving("1 scoop", 30))
    assert updated.servings == (Serving("1 scoop", 30),)
    again = store.add_serving(f.id, Serving("1 scoop", 32))
    assert again.servings == (Serving("1 scoop", 32),)
    with pytest.raises(NotFound):
        store.add_serving(999, Serving("x", 1))


def test_search_prefix_and_umlauts(store):
    haferflocken = store.upsert_food(food("Haferflocken", "a"))
    store.upsert_food(food("Sojadrink", "b"))
    store.upsert_food(food("Käsebrot", "c"))
    assert [f.id for f in store.search_foods("hafer")] == [haferflocken.id]
    assert [f.name for f in store.search_foods("soja")] == ["Sojadrink"]
    assert [f.name for f in store.search_foods("kase")] == ["Käsebrot"]
    assert [f.name for f in store.search_foods("KÄSE")] == ["Käsebrot"]


def test_search_brand_and_multiple_words(store):
    store.upsert_food(food("Muesli", "a", brand="Berg Farm"))
    store.upsert_food(food("Muesli", "b", brand="Tal Mill"))
    assert [f.brand for f in store.search_foods("muesli berg")] == ["Berg Farm"]


def test_search_ranks_exact_then_shorter(store):
    store.upsert_food(food("Oat Flakes Organic Extra", "a"))
    short = store.upsert_food(food("Oat Flakes", "b"))
    mid = store.upsert_food(food("Oat Flakes Fine", "c"))
    names = [f.name for f in store.search_foods("oat flakes")]
    assert names[0] == "Oat Flakes"
    assert names[1] == "Oat Flakes Fine"
    assert store.search_foods("oat flakes")[0].id == short.id
    assert mid.id in [f.id for f in store.search_foods("oat")]


def test_search_limit_empty_and_operators(store):
    for i in range(5):
        store.upsert_food(food(f"Bean {i}", str(i)))
    assert len(store.search_foods("bean", limit=3)) == 3
    assert store.search_foods("") == []
    assert store.search_foods("   ") == []
    assert store.search_foods('"') == []
    # Operators are plain words, so this is an AND of prefixes.
    assert store.search_foods("bean OR NOT (") == []


# Entries


def test_log_and_get_entry(store):
    f = store.upsert_food(food())
    e = log(
        store,
        at("2026-06-10", 8, 15),
        food_id=f.id,
        grams=50,
        servings=1.5,
        confidence=Confidence.HIGH,
        assumptions="weighed",
        origin_ref="ref:1",
    )
    got = store.get_entry(e.id)
    assert got == e
    assert e.eaten_at == at("2026-06-10", 8, 15)
    assert e.eaten_at.utcoffset() is not None
    assert (e.grams, e.servings, e.food_id) == (50, 1.5, f.id)
    assert (e.confidence, e.assumptions, e.origin_ref) == (Confidence.HIGH, "weighed", "ref:1")


def test_naive_datetime_is_rejected(store):
    with pytest.raises(ValueError):
        log(store, datetime(2026, 6, 10, 8, 0))
    e = log(store, at("2026-06-10", 8))
    with pytest.raises(ValueError):
        store.update_entry(e.id, eaten_at=datetime(2026, 6, 10, 9, 0))
    with pytest.raises(ValueError):
        store.entries_between(datetime(2026, 6, 10), at("2026-06-11", 0))


def test_other_timezone_is_normalised(store):
    tokyo = datetime(2026, 6, 10, 15, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    e = log(store, tokyo)
    assert e.eaten_at == tokyo
    assert e.eaten_at.utcoffset() == timedelta(hours=2)  # shown in local time


def test_duplicate_origin_ref(store):
    log(store, at("2026-06-10", 8), origin_ref="tandoor-cooklog:1")
    with pytest.raises(DuplicateEntry):
        log(store, at("2026-06-10", 9), origin_ref="tandoor-cooklog:1")
    assert len(store.entries_between(at("2026-06-10", 0), at("2026-06-11", 0))) == 1
    log(store, at("2026-06-10", 9), origin_ref=None)
    log(store, at("2026-06-10", 10), origin_ref=None)


def test_log_entry_unknown_food(store):
    with pytest.raises(NotFound):
        log(store, at("2026-06-10", 8), food_id=999)


def test_get_delete_not_found(store):
    with pytest.raises(NotFound):
        store.get_entry(1)
    with pytest.raises(NotFound):
        store.delete_entry(1)
    with pytest.raises(NotFound):
        store.update_entry(1, grams=10)


def test_delete_entry(store):
    e = log(store, at("2026-06-10", 8))
    store.delete_entry(e.id)
    with pytest.raises(NotFound):
        store.get_entry(e.id)


def test_update_grams_rescales_snapshot(store):
    e = log(store, at("2026-06-10", 8), kcal=200, protein=20, grams=100)
    updated = store.update_entry(e.id, grams=150)
    assert updated.grams == 150
    assert updated.nutrients.kcal == pytest.approx(300)
    assert updated.nutrients.protein_g == pytest.approx(30)
    assert updated.nutrients.fibre_g is None
    assert store.get_entry(e.id) == updated


def test_update_servings_rescales_snapshot(store):
    e = log(store, at("2026-06-10", 8), kcal=200, servings=2)
    updated = store.update_entry(e.id, servings=1)
    assert updated.servings == 1
    assert updated.nutrients.kcal == pytest.approx(100)
    assert updated.grams is None


def test_update_time_only_keeps_nutrients(store):
    e = log(store, at("2026-06-10", 8), kcal=200)
    updated = store.update_entry(e.id, eaten_at=at("2026-06-10", 12))
    assert updated.eaten_at == at("2026-06-10", 12)
    assert updated.nutrients == e.nutrients


def test_update_without_an_amount_to_scale_raises(store):
    e = log(store, at("2026-06-10", 8))
    with pytest.raises(ValueError):
        store.update_entry(e.id, grams=10)
    with pytest.raises(ValueError):
        store.update_entry(e.id, servings=1)
    g = log(store, at("2026-06-10", 9), grams=100)
    with pytest.raises(ValueError):
        store.update_entry(g.id, servings=2)
    with pytest.raises(ValueError):
        store.update_entry(g.id, grams=0)
    assert store.get_entry(g.id).nutrients == g.nutrients


def test_entries_between_is_half_open_and_ordered(store):
    b = log(store, at("2026-06-10", 12))
    a = log(store, at("2026-06-10", 8))
    log(store, at("2026-06-10", 18))
    got = store.entries_between(at("2026-06-10", 8), at("2026-06-10", 18))
    assert [e.id for e in got] == [a.id, b.id]


def test_deleting_a_food_keeps_entries(store):
    f = store.upsert_food(food())
    e = log(store, at("2026-06-10", 8), food_id=f.id)
    store._db.execute("DELETE FROM foods WHERE id = ?", (f.id,))
    assert store.get_entry(e.id).food_id is None
    assert store.search_foods("oat") == []


# Goals


def test_set_goal_validates(store):
    with pytest.raises(ValueError):
        store.set_goal(Goal("sodium", GoalKind.MAX, date(2026, 6, 1), max=1))
    with pytest.raises(ValueError):
        store.set_goal(Goal("kcal", GoalKind.BAND, date(2026, 6, 1), min=1))
    with pytest.raises(ValueError):
        store.set_goal(Goal("kcal", GoalKind.MIN, date(2026, 6, 1)))


def test_goal_change_mid_week_keeps_old_days(store):
    store.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 6, 1), min=100))
    store.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 6, 4), min=150))
    store.set_goal(Goal("kcal", GoalKind.MAX, date(2026, 6, 2), max=2500))
    for d in range(1, 8):
        log(store, at(f"2026-06-0{d}", 12), kcal=500, protein=120)
    week = store.week_summary(date(2026, 6, 1))
    assert [s.day for s in week] == [date(2026, 6, 1) + timedelta(days=i) for i in range(7)]
    protein = [next(g for g in s.goals if g.goal.nutrient == "protein_g") for s in week]
    assert [g.goal.min for g in protein] == [100, 100, 100, 150, 150, 150, 150]
    assert [g.met for g in protein] == [True, True, True, False, False, False, False]
    assert [len(s.goals) for s in week] == [1, 2, 2, 2, 2, 2, 2]


def test_goals_on_picks_latest_valid_from(store):
    assert store.goals_on(date(2026, 6, 1)) == []
    store.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 6, 10), min=130))
    store.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 6, 1), min=100))
    store.set_goal(Goal("fat_g", GoalKind.MAX, date(2026, 6, 1), max=80))
    assert store.goals_on(date(2026, 5, 31)) == []
    assert [g.min for g in store.goals_on(date(2026, 6, 9)) if g.nutrient == "protein_g"] == [100]
    assert [g.nutrient for g in store.goals_on(date(2026, 6, 10))] == ["protein_g", "fat_g"]
    assert store.goals_on(date(2026, 6, 10))[0].min == 130


def test_same_day_goal_is_replaced(store):
    store.set_goal(Goal("kcal", GoalKind.MAX, date(2026, 6, 1), max=2000))
    store.set_goal(Goal("kcal", GoalKind.MAX, date(2026, 6, 1), max=2200))
    assert [g.max for g in store.goals_on(date(2026, 6, 1))] == [2200]


def test_goal_status_kinds(store):
    day = date(2026, 6, 10)
    store.set_goal(Goal("protein_g", GoalKind.MIN, day, min=50))
    store.set_goal(Goal("kcal", GoalKind.BAND, day, min=1800, max=2200))
    store.set_goal(Goal("fat_g", GoalKind.MAX, day, max=1))
    store.set_goal(Goal("fibre_g", GoalKind.MIN, day, min=10))
    log(store, at("2026-06-10", 8), kcal=1000, protein=50)
    log(store, at("2026-06-10", 13), kcal=1000, protein=1)
    by_name = {s.goal.nutrient: s for s in store.day_summary(day).goals}
    assert by_name["protein_g"].value == 51 and by_name["protein_g"].met
    assert by_name["kcal"].value == 2000 and by_name["kcal"].met
    assert by_name["fat_g"].value == 2 and not by_name["fat_g"].met
    assert by_name["fibre_g"].value == 0 and not by_name["fibre_g"].met


def test_band_edges(store):
    day = date(2026, 6, 10)
    store.set_goal(Goal("kcal", GoalKind.BAND, day, min=100, max=200))
    for kcal, met in [(99, False), (100, True), (200, True), (201, False)]:
        e = log(store, at("2026-06-10", 8), kcal=kcal)
        assert store.day_summary(day).goals[0].met is met
        store.delete_entry(e.id)


# Summaries


def test_meal_grouping_at_the_gap_boundary(store):
    a = log(store, at("2026-06-10", 8, 0))
    b = log(store, at("2026-06-10", 9, 29), kcal=50, protein=5)  # 89 min after a
    c = log(store, at("2026-06-10", 10, 59))  # exactly 90 min after b: new meal
    d = log(store, at("2026-06-10", 20, 0))
    s = store.day_summary(date(2026, 6, 10))
    assert [[e.id for e in m.entries] for m in s.meals] == [[a.id, b.id], [c.id], [d.id]]
    assert s.meals[0].start == at("2026-06-10", 8)
    assert s.meals[0].totals.kcal == 150
    assert s.meals[0].totals.protein_g == 15
    assert s.totals.kcal == 350


def test_meal_gap_is_between_neighbours(store):
    times = [(8, 0), (9, 20), (10, 40), (12, 0)]
    for hh, mm in times:
        log(store, at("2026-06-10", hh, mm))
    assert len(store.day_summary(date(2026, 6, 10)).meals) == 1


def test_empty_day(store):
    s = store.day_summary(date(2026, 6, 10))
    assert s.meals == ()
    assert s.totals == Nutrients.zero()
    assert s.estimated_share == 0.0


def test_day_bounds_are_local_midnight(store):
    log(store, at("2026-06-09", 23, 59), name="before")
    inside = log(store, at("2026-06-10", 0, 0), name="first")
    last = log(store, at("2026-06-10", 23, 59), name="last")
    log(store, at("2026-06-11", 0, 0), name="after")
    entries = [e for m in store.day_summary(date(2026, 6, 10)).meals for e in m.entries]
    assert [e.id for e in entries] == [inside.id, last.id]


def test_spring_forward_day_is_23_hours(store):
    log(store, at("2026-03-28", 23, 30))
    a = log(store, at("2026-03-29", 0, 30))
    b = log(store, at("2026-03-29", 23, 30))
    log(store, at("2026-03-30", 0, 30))
    s = store.day_summary(date(2026, 3, 29))
    assert [e.id for m in s.meals for e in m.entries] == [a.id, b.id]
    lo = at("2026-03-29", 0)
    hi = at("2026-03-30", 0)
    assert hi.astimezone(UTC) - lo.astimezone(UTC) == timedelta(hours=23)


def test_fall_back_day_is_25_hours(store):
    log(store, at("2026-10-24", 23, 30))
    first = log(store, at("2026-10-25", 0, 30))
    early = log(store, at("2026-10-25", 2, 30, fold=0))  # still summer time
    late = log(store, at("2026-10-25", 2, 30, fold=1))  # repeated hour, winter time
    last = log(store, at("2026-10-25", 23, 30))
    log(store, at("2026-10-26", 0, 30))
    s = store.day_summary(date(2026, 10, 25))
    ids = [e.id for m in s.meals for e in m.entries]
    assert ids == [first.id, early.id, late.id, last.id]
    assert at("2026-10-26", 0).astimezone(UTC) - at("2026-10-25", 0).astimezone(UTC) == timedelta(hours=25)
    assert early.eaten_at.utcoffset() != late.eaten_at.utcoffset()


def test_meal_gap_counts_real_minutes_across_spring_forward(store):
    a = log(store, at("2026-03-29", 1, 10))
    b = log(store, at("2026-03-29", 3, 30))  # 80 real minutes later, 140 on the wall clock
    s = store.day_summary(date(2026, 3, 29))
    assert [[e.id for e in m.entries] for m in s.meals] == [[a.id, b.id]]


def test_meal_gap_counts_real_minutes_across_fall_back(store):
    a = log(store, at("2026-10-25", 2, 10, fold=0))
    b = log(store, at("2026-10-25", 2, 50, fold=1))  # 100 real minutes later, 40 on the wall clock
    s = store.day_summary(date(2026, 10, 25))
    assert [[e.id for e in m.entries] for m in s.meals] == [[a.id], [b.id]]


def test_estimated_share(store):
    log(store, at("2026-06-10", 8), kcal=300, source=Source.LABEL)
    log(store, at("2026-06-10", 12), kcal=100, source=Source.AI_ESTIMATE)
    s = store.day_summary(date(2026, 6, 10))
    assert s.estimated_share == pytest.approx(0.25)


def test_estimated_share_zero_kcal(store):
    log(store, at("2026-06-10", 8), kcal=0, source=Source.AI_ESTIMATE)
    assert store.day_summary(date(2026, 6, 10)).estimated_share == 0.0


def test_fibre_total_stays_none_until_reported(store):
    log(store, at("2026-06-10", 8))
    assert store.day_summary(date(2026, 6, 10)).totals.fibre_g is None
    store.log_entry(
        name="With fibre",
        nutrients=n(fibre=3),
        eaten_at=at("2026-06-10", 12),
        source=Source.MANUAL,
        origin=Origin.UI,
    )
    assert store.day_summary(date(2026, 6, 10)).totals.fibre_g == 3


# Quick items


def test_quick_items(store):
    f = store.upsert_food(food())
    a = store.add_quick_item(f.id, 40, "Porridge")
    b = store.add_quick_item(f.id, 250, "Big bowl")
    c = store.add_quick_item(f.id, 10, "Pinch")
    assert [q.label for q in store.quick_items()] == ["Porridge", "Big bowl", "Pinch"]
    assert [q.position for q in store.quick_items()] == [0, 1, 2]
    assert (a.food_id, a.grams) == (f.id, 40)
    store.remove_quick_item(b.id)
    d = store.add_quick_item(f.id, 5, "Last")
    assert [q.label for q in store.quick_items()] == ["Porridge", "Pinch", "Last"]
    assert d.position > c.position
    with pytest.raises(NotFound):
        store.remove_quick_item(b.id)
    with pytest.raises(NotFound):
        store.add_quick_item(999, 1, "x")


def test_quick_items_follow_food_deletion(store):
    f = store.upsert_food(food())
    store.add_quick_item(f.id, 40, "Porridge")
    store._db.execute("DELETE FROM foods WHERE id = ?", (f.id,))
    assert store.quick_items() == []


# Persistence


def test_file_database_survives_reopen(tmp_path):
    path = tmp_path / "log.sqlite"
    first = Store(path)
    f = first.upsert_food(food("Haferflocken", "a", servings=(Serving("1 bowl", 40),)))
    e = log(first, at("2026-06-10", 8), food_id=f.id, grams=40, origin_ref="ref:1")
    first.set_goal(Goal("protein_g", GoalKind.MIN, date(2026, 6, 1), min=100))
    q = first.add_quick_item(f.id, 40, "Porridge")
    first.close()

    second = Store(path)
    assert second.get_food(f.id) == f
    assert second.get_entry(e.id) == e
    assert [g.min for g in second.goals_on(date(2026, 6, 10))] == [100]
    assert second.quick_items() == [q]
    assert [x.id for x in second.search_foods("hafer")] == [f.id]
    with pytest.raises(DuplicateEntry):
        log(second, at("2026-06-10", 9), origin_ref="ref:1")
    second.close()


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "log.sqlite"
    Store(path).close()
    import sqlite3

    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.close()
    with pytest.raises(RuntimeError):
        Store(path)


def test_use_from_another_thread(store):
    import threading

    errors = []

    def work():
        try:
            for i in range(20):
                log(store, at("2026-06-10", 8) + timedelta(minutes=i))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(store.entries_between(at("2026-06-10", 0), at("2026-06-11", 0))) == 80
