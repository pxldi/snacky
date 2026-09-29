"""The log: one SQLite file, owned by one process.

Only this module writes the database. The MCP tools and the web UI call it;
neither opens the file themselves.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from snacky.model import (
    Confidence,
    DaySummary,
    Entry,
    Food,
    FoodCandidate,
    Goal,
    Nutrients,
    Origin,
    QuickItem,
    Serving,
    Source,
)


class DuplicateEntry(Exception):
    """An entry with this origin_ref already exists. The evening check relies
    on this to never log the same Tandoor cook log twice."""


class NotFound(Exception):
    pass


class Store:
    def __init__(self, path: str | Path) -> None:
        """Open (and create) the database at `path`. ":memory:" works for tests."""
        raise NotImplementedError

    def migrate(self) -> None:
        """Create or upgrade the schema. Safe to call on every start."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    # Foods

    def upsert_food(self, candidate: FoodCandidate) -> Food:
        """Store a food from a source. A candidate with the same (source,
        source_ref) as a stored food updates it and returns the same id."""
        raise NotImplementedError

    def get_food(self, food_id: int) -> Food:
        """Raises NotFound."""
        raise NotImplementedError

    def search_foods(self, query: str, limit: int = 10) -> list[Food]:
        """Search stored foods by name and brand, best match first. This is the
        first step of every lookup, so a food logged once is found again
        without asking a database."""
        raise NotImplementedError

    def add_serving(self, food_id: int, serving: Serving) -> Food:
        raise NotImplementedError

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
        raise NotImplementedError

    def get_entry(self, entry_id: int) -> Entry:
        """Raises NotFound."""
        raise NotImplementedError

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
        raise NotImplementedError

    def delete_entry(self, entry_id: int) -> None:
        """Raises NotFound."""
        raise NotImplementedError

    def entries_between(self, start: datetime, end: datetime) -> list[Entry]:
        """Entries with start <= eaten_at < end, oldest first."""
        raise NotImplementedError

    # Goals

    def set_goal(self, goal: Goal) -> None:
        """Add a goal. It applies from goal.valid_from until the next goal for
        the same nutrient; older days keep the goal that applied then."""
        raise NotImplementedError

    def goals_on(self, day: date) -> list[Goal]:
        """The goal per nutrient that applies on `day`."""
        raise NotImplementedError

    # Summaries

    def day_summary(self, day: date) -> DaySummary:
        """Totals, meals and goal status for one local day (see snacky.config.TZ).
        Entries less than MEAL_GAP apart form one meal."""
        raise NotImplementedError

    def week_summary(self, start: date) -> list[DaySummary]:
        """Seven day summaries from `start`."""
        raise NotImplementedError

    # Quick items

    def quick_items(self) -> list[QuickItem]:
        raise NotImplementedError

    def add_quick_item(self, food_id: int, grams: float, label: str) -> QuickItem:
        raise NotImplementedError

    def remove_quick_item(self, item_id: int) -> None:
        raise NotImplementedError
