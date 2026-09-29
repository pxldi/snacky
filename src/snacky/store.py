"""The log: one SQLite file, owned by one process.

Only this module writes the database. The MCP tools and the web UI call it;
neither opens the file themselves.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from snacky import config
from snacky.model import (
    Confidence,
    DaySummary,
    Entry,
    Food,
    FoodCandidate,
    Goal,
    GoalKind,
    GoalStatus,
    Meal,
    Nutrients,
    Origin,
    QuickItem,
    Serving,
    Source,
)

NUTRIENT_FIELDS = tuple(f.name for f in fields(Nutrients))

# Each step upgrades the schema by one version. Never edit a step that has
# shipped; add a new one.
_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE foods (
        id         INTEGER PRIMARY KEY,
        name       TEXT NOT NULL,
        brand      TEXT,
        source     TEXT NOT NULL,
        source_ref TEXT,
        kcal       REAL NOT NULL,
        protein_g  REAL NOT NULL,
        fat_g      REAL NOT NULL,
        carbs_g    REAL NOT NULL,
        fibre_g    REAL,
        extra      TEXT NOT NULL DEFAULT '{}'
    );
    CREATE UNIQUE INDEX foods_source_ref
        ON foods (source, source_ref) WHERE source_ref IS NOT NULL;

    CREATE TABLE servings (
        id      INTEGER PRIMARY KEY,
        food_id INTEGER NOT NULL REFERENCES foods (id) ON DELETE CASCADE,
        label   TEXT NOT NULL,
        grams   REAL NOT NULL,
        UNIQUE (food_id, label)
    );

    CREATE VIRTUAL TABLE foods_fts USING fts5(
        name, brand,
        content = 'foods', content_rowid = 'id',
        tokenize = "unicode61 remove_diacritics 2"
    );
    CREATE TRIGGER foods_ai AFTER INSERT ON foods BEGIN
        INSERT INTO foods_fts (rowid, name, brand) VALUES (new.id, new.name, new.brand);
    END;
    CREATE TRIGGER foods_ad AFTER DELETE ON foods BEGIN
        INSERT INTO foods_fts (foods_fts, rowid, name, brand)
            VALUES ('delete', old.id, old.name, old.brand);
    END;
    CREATE TRIGGER foods_au AFTER UPDATE ON foods BEGIN
        INSERT INTO foods_fts (foods_fts, rowid, name, brand)
            VALUES ('delete', old.id, old.name, old.brand);
        INSERT INTO foods_fts (rowid, name, brand) VALUES (new.id, new.name, new.brand);
    END;

    CREATE TABLE entries (
        id          INTEGER PRIMARY KEY,
        eaten_at    TEXT NOT NULL,
        name        TEXT NOT NULL,
        kcal        REAL NOT NULL,
        protein_g   REAL NOT NULL,
        fat_g       REAL NOT NULL,
        carbs_g     REAL NOT NULL,
        fibre_g     REAL,
        grams       REAL,
        servings    REAL,
        food_id     INTEGER REFERENCES foods (id) ON DELETE SET NULL,
        source      TEXT NOT NULL,
        origin      TEXT NOT NULL,
        confidence  TEXT,
        assumptions TEXT,
        origin_ref  TEXT UNIQUE
    );
    CREATE INDEX entries_eaten_at ON entries (eaten_at);

    CREATE TABLE goals (
        nutrient   TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        kind       TEXT NOT NULL,
        min        REAL,
        max        REAL,
        PRIMARY KEY (nutrient, valid_from)
    );

    CREATE TABLE quick_items (
        id       INTEGER PRIMARY KEY,
        food_id  INTEGER NOT NULL REFERENCES foods (id) ON DELETE CASCADE,
        grams    REAL NOT NULL,
        label    TEXT NOT NULL,
        position INTEGER NOT NULL
    );
    """,
)


def _utc_text(value: datetime) -> str:
    """Fixed-width UTC text, so string order is time order."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _from_text(value: str) -> datetime:
    # Local time on the way out, so the UI shows what the eater saw.
    return datetime.fromisoformat(value).astimezone(config.TZ)


def _fts_query(query: str) -> str | None:
    """Every word becomes a quoted prefix term. Quoting keeps FTS5 operators
    typed by a user from being parsed."""
    words = re.findall(r"\w+", query)
    if not words:
        return None
    return " ".join(f'"{word}"*' for word in words)


def _nutrients(row: sqlite3.Row) -> Nutrients:
    return Nutrients(
        kcal=row["kcal"],
        protein_g=row["protein_g"],
        fat_g=row["fat_g"],
        carbs_g=row["carbs_g"],
        fibre_g=row["fibre_g"],
    )


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        eaten_at=_from_text(row["eaten_at"]),
        name=row["name"],
        nutrients=_nutrients(row),
        source=Source(row["source"]),
        origin=Origin(row["origin"]),
        grams=row["grams"],
        servings=row["servings"],
        food_id=row["food_id"],
        confidence=Confidence(row["confidence"]) if row["confidence"] else None,
        assumptions=row["assumptions"],
        origin_ref=row["origin_ref"],
    )


def _goal(row: sqlite3.Row) -> Goal:
    return Goal(
        nutrient=row["nutrient"],
        kind=GoalKind(row["kind"]),
        valid_from=date.fromisoformat(row["valid_from"]),
        min=row["min"],
        max=row["max"],
    )


def _goal_met(goal: Goal, value: float) -> bool:
    if goal.kind is GoalKind.MIN:
        return goal.min is not None and value >= goal.min
    if goal.kind is GoalKind.MAX:
        return goal.max is not None and value <= goal.max
    return goal.min is not None and goal.max is not None and goal.min <= value <= goal.max


class DuplicateEntry(Exception):
    """An entry with this origin_ref already exists. The evening check relies
    on this to never log the same Tandoor cook log twice."""


class NotFound(Exception):
    pass


class Store:
    def __init__(self, path: str | Path) -> None:
        """Open (and create) the database at `path`. ":memory:" works for tests."""
        # The MCP server and the web UI share one connection from asyncio
        # threads, so the lock below serialises every access. Re-entrant so a
        # summary can hold it across the reads it is built from.
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._db

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def migrate(self) -> None:
        """Create or upgrade the schema. Safe to call on every start."""
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(_MIGRATIONS):
                raise RuntimeError(f"database schema {version} is newer than this code ({len(_MIGRATIONS)})")
            for target in range(version + 1, len(_MIGRATIONS) + 1):
                # executescript would commit first, so the transaction is in the script.
                script = f"BEGIN; {_MIGRATIONS[target - 1]} PRAGMA user_version = {target}; COMMIT;"
                try:
                    self._db.executescript(script)
                except BaseException:
                    if self._db.in_transaction:
                        self._db.execute("ROLLBACK")
                    raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # Foods

    def _food(self, db: sqlite3.Connection, food_id: int) -> Food:
        row = db.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
        if row is None:
            raise NotFound(f"food {food_id}")
        return self._food_from_row(db, row)

    def _food_from_row(self, db: sqlite3.Connection, row: sqlite3.Row) -> Food:
        servings = db.execute(
            "SELECT label, grams FROM servings WHERE food_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
        return Food(
            id=row["id"],
            name=row["name"],
            source=Source(row["source"]),
            per_100g=_nutrients(row),
            source_ref=row["source_ref"],
            brand=row["brand"],
            servings=tuple(Serving(s["label"], s["grams"]) for s in servings),
            extra=json.loads(row["extra"]),
        )

    @staticmethod
    def _put_serving(db: sqlite3.Connection, food_id: int, serving: Serving) -> None:
        # Same label updates the grams and keeps the row.
        db.execute(
            "INSERT INTO servings (food_id, label, grams) VALUES (?, ?, ?) "
            "ON CONFLICT (food_id, label) DO UPDATE SET grams = excluded.grams",
            (food_id, serving.label, serving.grams),
        )

    def upsert_food(self, candidate: FoodCandidate) -> Food:
        """Store a food from a source. A candidate with the same (source,
        source_ref) as a stored food updates it and returns the same id."""
        n = candidate.per_100g
        values = (
            candidate.name,
            candidate.brand,
            n.kcal,
            n.protein_g,
            n.fat_g,
            n.carbs_g,
            n.fibre_g,
            json.dumps(candidate.extra, sort_keys=True),
        )
        with self._write() as db:
            existing = None
            if candidate.source_ref is not None:
                existing = db.execute(
                    "SELECT id FROM foods WHERE source = ? AND source_ref = ?",
                    (candidate.source.value, candidate.source_ref),
                ).fetchone()
            if existing is not None:
                food_id = existing["id"]
                db.execute(
                    "UPDATE foods SET name = ?, brand = ?, kcal = ?, protein_g = ?, "
                    "fat_g = ?, carbs_g = ?, fibre_g = ?, extra = ? WHERE id = ?",
                    (*values, food_id),
                )
            else:
                food_id = db.execute(
                    "INSERT INTO foods (name, brand, kcal, protein_g, fat_g, carbs_g, "
                    "fibre_g, extra, source, source_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, candidate.source.value, candidate.source_ref),
                ).lastrowid
            # Servings are merged, not replaced, so ones added by hand survive a refresh.
            for serving in candidate.servings:
                self._put_serving(db, food_id, serving)
            return self._food(db, food_id)

    def get_food(self, food_id: int) -> Food:
        """Raises NotFound."""
        with self._read() as db:
            return self._food(db, food_id)

    def food_by_source_ref(self, source: Source, source_ref: str) -> Food | None:
        """The stored food with this (source, source_ref), or None."""
        with self._read() as db:
            row = db.execute(
                "SELECT * FROM foods WHERE source = ? AND source_ref = ?", (source.value, source_ref)
            ).fetchone()
            return None if row is None else self._food_from_row(db, row)

    def search_foods(self, query: str, limit: int = 10) -> list[Food]:
        """Search stored foods by name and brand, best match first. This is the
        first step of every lookup, so a food logged once is found again
        without asking a database."""
        match = _fts_query(query)
        if match is None or limit <= 0:
            return []
        with self._read() as db:
            rows = db.execute(
                "SELECT f.* FROM foods_fts JOIN foods f ON f.id = foods_fts.rowid "
                "WHERE foods_fts MATCH ? "
                "ORDER BY lower(f.name) = lower(?) DESC, length(f.name), "
                "bm25(foods_fts), f.id LIMIT ?",
                (match, query.strip(), limit),
            ).fetchall()
            return [self._food_from_row(db, row) for row in rows]

    def add_serving(self, food_id: int, serving: Serving) -> Food:
        with self._write() as db:
            self._food(db, food_id)
            self._put_serving(db, food_id, serving)
            return self._food(db, food_id)

    # Entries

    def log_entry(
        self,
        *,
        name: str,
        nutrients: Nutrients,
        eaten_at: datetime,
        source: Source,
        origin: Origin,
        grams: float | None = None,
        servings: float | None = None,
        food_id: int | None = None,
        confidence: Confidence | None = None,
        assumptions: str | None = None,
        origin_ref: str | None = None,
    ) -> Entry:
        """Log one thing eaten. `nutrients` is the absolute amount and is
        stored as a snapshot. Raises DuplicateEntry when origin_ref exists."""
        when = _utc_text(eaten_at)
        with self._write() as db:
            if (
                origin_ref is not None
                and db.execute("SELECT 1 FROM entries WHERE origin_ref = ?", (origin_ref,)).fetchone()
            ):
                raise DuplicateEntry(origin_ref)
            if food_id is not None:
                self._food(db, food_id)
            entry_id = db.execute(
                "INSERT INTO entries (eaten_at, name, kcal, protein_g, fat_g, carbs_g, "
                "fibre_g, grams, servings, food_id, source, origin, confidence, "
                "assumptions, origin_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    when,
                    name,
                    nutrients.kcal,
                    nutrients.protein_g,
                    nutrients.fat_g,
                    nutrients.carbs_g,
                    nutrients.fibre_g,
                    grams,
                    servings,
                    food_id,
                    source.value,
                    origin.value,
                    confidence.value if confidence else None,
                    assumptions,
                    origin_ref,
                ),
            ).lastrowid
            return self._entry(db, entry_id)

    @staticmethod
    def _entry(db: sqlite3.Connection, entry_id: int) -> Entry:
        row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise NotFound(f"entry {entry_id}")
        return _entry(row)

    def get_entry(self, entry_id: int) -> Entry:
        """Raises NotFound."""
        with self._read() as db:
            return self._entry(db, entry_id)

    def update_entry(
        self,
        entry_id: int,
        *,
        grams: float | None = None,
        servings: float | None = None,
        eaten_at: datetime | None = None,
    ) -> Entry:
        """Change the amount or the time. A new amount rescales the snapshot in
        proportion to the old one. Raises NotFound."""
        when = _utc_text(eaten_at) if eaten_at is not None else None
        for amount in (grams, servings):
            if amount is not None and amount <= 0:
                raise ValueError("amount must be positive")
        with self._write() as db:
            old = self._entry(db, entry_id)
            new_grams, new_servings = old.grams, old.servings
            factor = None
            # Grams win when both are given, so the snapshot is scaled once.
            if grams is not None:
                if not old.grams:
                    raise ValueError("entry has no grams to rescale from")
                factor, new_grams = grams / old.grams, grams
            if servings is not None:
                if not old.servings:
                    raise ValueError("entry has no servings to rescale from")
                new_servings = servings
                if factor is None:
                    factor = servings / old.servings
            nutrients = old.nutrients if factor is None else old.nutrients.scaled(factor)
            db.execute(
                "UPDATE entries SET eaten_at = COALESCE(?, eaten_at), kcal = ?, protein_g = ?, "
                "fat_g = ?, carbs_g = ?, fibre_g = ?, grams = ?, servings = ? WHERE id = ?",
                (
                    when,
                    nutrients.kcal,
                    nutrients.protein_g,
                    nutrients.fat_g,
                    nutrients.carbs_g,
                    nutrients.fibre_g,
                    new_grams,
                    new_servings,
                    entry_id,
                ),
            )
            return self._entry(db, entry_id)

    def delete_entry(self, entry_id: int) -> None:
        """Raises NotFound."""
        with self._write() as db:
            if db.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount == 0:
                raise NotFound(f"entry {entry_id}")

    def entries_between(self, start: datetime, end: datetime) -> list[Entry]:
        """Entries with start <= eaten_at < end, oldest first."""
        lo, hi = _utc_text(start), _utc_text(end)
        with self._read() as db:
            rows = db.execute(
                "SELECT * FROM entries WHERE eaten_at >= ? AND eaten_at < ? ORDER BY eaten_at, id",
                (lo, hi),
            ).fetchall()
            return [_entry(row) for row in rows]

    # Goals

    def set_goal(self, goal: Goal) -> None:
        """Add a goal. It applies from goal.valid_from until the next goal for
        the same nutrient; older days keep the goal that applied then."""
        if goal.nutrient not in NUTRIENT_FIELDS:
            raise ValueError(f"unknown nutrient {goal.nutrient!r}")
        needs_min = goal.kind in (GoalKind.MIN, GoalKind.BAND)
        needs_max = goal.kind in (GoalKind.MAX, GoalKind.BAND)
        if (needs_min and goal.min is None) or (needs_max and goal.max is None):
            raise ValueError(f"a {goal.kind.value} goal needs its bounds")
        with self._write() as db:
            # The same nutrient and date replaces the earlier goal.
            db.execute(
                "INSERT OR REPLACE INTO goals (nutrient, valid_from, kind, min, max) VALUES (?, ?, ?, ?, ?)",
                (goal.nutrient, goal.valid_from.isoformat(), goal.kind.value, goal.min, goal.max),
            )

    def _goals_on(self, db: sqlite3.Connection, day: date) -> list[Goal]:
        rows = db.execute(
            "SELECT * FROM goals g WHERE valid_from = ("
            "SELECT max(valid_from) FROM goals WHERE nutrient = g.nutrient AND valid_from <= ?)",
            (day.isoformat(),),
        ).fetchall()
        goals = [_goal(row) for row in rows]
        return sorted(goals, key=lambda g: NUTRIENT_FIELDS.index(g.nutrient))

    def goals_on(self, day: date) -> list[Goal]:
        """The goal per nutrient that applies on `day`."""
        with self._read() as db:
            return self._goals_on(db, day)

    # Summaries

    def day_summary(self, day: date) -> DaySummary:
        """Totals, meals and goal status for one local day (see snacky.config.TZ).
        Entries less than MEAL_GAP apart form one meal."""
        # Built from local midnights, not 24 h, so a DST day is 23 or 25 hours long.
        start = datetime.combine(day, time.min, tzinfo=config.TZ)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=config.TZ)
        with self._read() as db:
            entries = self.entries_between(start, end)
            goals = self._goals_on(db, day)

        groups: list[list[Entry]] = []
        for entry in entries:
            # Both sides share one tzinfo, and Python then subtracts wall clocks, which is
            # wrong across a DST change. UTC gives the real elapsed time.
            if groups and _utc(entry.eaten_at) - _utc(groups[-1][-1].eaten_at) < config.MEAL_GAP:
                groups[-1].append(entry)
            else:
                groups.append([entry])
        meals = tuple(
            Meal(
                start=group[0].eaten_at,
                entries=tuple(group),
                totals=sum((e.nutrients for e in group), Nutrients.zero()),
            )
            for group in groups
        )
        totals = sum((m.totals for m in meals), Nutrients.zero())
        statuses = []
        for goal in goals:
            value = getattr(totals, goal.nutrient) or 0.0
            statuses.append(GoalStatus(goal=goal, value=value, met=_goal_met(goal, value)))
        estimated = sum(e.nutrients.kcal for e in entries if e.source is Source.AI_ESTIMATE)
        return DaySummary(
            day=day,
            totals=totals,
            meals=meals,
            goals=tuple(statuses),
            estimated_share=estimated / totals.kcal if totals.kcal else 0.0,
        )

    def week_summary(self, start: date) -> list[DaySummary]:
        """Seven day summaries from `start`."""
        return [self.day_summary(start + timedelta(days=i)) for i in range(7)]

    # Quick items

    @staticmethod
    def _quick(row: sqlite3.Row) -> QuickItem:
        return QuickItem(
            id=row["id"],
            food_id=row["food_id"],
            grams=row["grams"],
            label=row["label"],
            position=row["position"],
        )

    def quick_items(self) -> list[QuickItem]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM quick_items ORDER BY position, id").fetchall()
            return [self._quick(row) for row in rows]

    def add_quick_item(self, food_id: int, grams: float, label: str) -> QuickItem:
        with self._write() as db:
            self._food(db, food_id)
            position = db.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM quick_items").fetchone()[0]
            item_id = db.execute(
                "INSERT INTO quick_items (food_id, grams, label, position) VALUES (?, ?, ?, ?)",
                (food_id, grams, label, position),
            ).lastrowid
            row: Any = db.execute("SELECT * FROM quick_items WHERE id = ?", (item_id,)).fetchone()
            return self._quick(row)

    def remove_quick_item(self, item_id: int) -> None:
        with self._write() as db:
            if db.execute("DELETE FROM quick_items WHERE id = ?", (item_id,)).rowcount == 0:
                raise NotFound(f"quick item {item_id}")
