"""The types every module shares. Sources return them, the store keeps them,
the MCP tools and the web UI read them. Changing one is an interface change
for every module, so it goes in its own pull request."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Source(StrEnum):
    """Where a food's numbers came from. The UI shows estimates differently."""

    BLS = "bls"
    OFF = "off"
    LABEL = "label"  # per-100 g values read off a packaging photo
    TANDOOR = "tandoor"  # a recipe's nutrition as Tandoor computes it
    MANUAL = "manual"
    AI_ESTIMATE = "ai_estimate"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Origin(StrEnum):
    """Which path wrote an entry."""

    CHAT = "chat"
    UI = "ui"
    TANDOOR = "tandoor"


class GoalKind(StrEnum):
    MIN = "min"
    MAX = "max"
    BAND = "band"


@dataclass(frozen=True)
class Nutrients:
    """An absolute amount, or an amount per 100 g when a field says per_100g.
    Fibre is None when the source does not report it, which is not the same
    as zero."""

    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    fibre_g: float | None = None

    def scaled(self, factor: float) -> Nutrients:
        return Nutrients(
            kcal=self.kcal * factor,
            protein_g=self.protein_g * factor,
            fat_g=self.fat_g * factor,
            carbs_g=self.carbs_g * factor,
            fibre_g=None if self.fibre_g is None else self.fibre_g * factor,
        )

    def for_grams(self, grams: float) -> Nutrients:
        """Absolute nutrients for `grams` of a food whose values are per 100 g."""
        return self.scaled(grams / 100)

    def __add__(self, other: Nutrients) -> Nutrients:
        fibre = (
            None
            if self.fibre_g is None and other.fibre_g is None
            else ((self.fibre_g or 0) + (other.fibre_g or 0))
        )
        return Nutrients(
            kcal=self.kcal + other.kcal,
            protein_g=self.protein_g + other.protein_g,
            fat_g=self.fat_g + other.fat_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fibre_g=fibre,
        )

    @staticmethod
    def zero() -> Nutrients:
        return Nutrients(0, 0, 0, 0, None)


@dataclass(frozen=True)
class Serving:
    """A named portion of a food, e.g. "1 Scoop" = 30 g."""

    label: str
    grams: float


@dataclass(frozen=True)
class FoodCandidate:
    """A food as a source returns it, before it is stored."""

    name: str
    source: Source
    per_100g: Nutrients
    source_ref: str | None = None  # BLS code, barcode, or Tandoor food id
    brand: str | None = None
    servings: tuple[Serving, ...] = ()
    # Everything else the source reports per 100 g, keyed by the source's own
    # nutrient code (BLS codes for BLS foods). Kept so micronutrients can be
    # computed later without logging again.
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Food:
    """A stored food."""

    id: int
    name: str
    source: Source
    per_100g: Nutrients
    source_ref: str | None = None
    brand: str | None = None
    servings: tuple[Serving, ...] = ()
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Entry:
    """One thing eaten. `nutrients` is a snapshot taken when it was logged."""

    id: int
    eaten_at: datetime  # timezone-aware
    name: str
    nutrients: Nutrients
    source: Source
    origin: Origin
    grams: float | None = None  # None for a recipe portion logged by servings
    servings: float | None = None
    food_id: int | None = None
    confidence: Confidence | None = None
    assumptions: str | None = None
    origin_ref: str | None = None  # e.g. "tandoor-cooklog:123"; unique when set


@dataclass(frozen=True)
class Goal:
    """A daily target that applies from `valid_from` until the next goal for
    the same nutrient. `nutrient` is a Nutrients field name, e.g. "protein_g"."""

    nutrient: str
    kind: GoalKind
    valid_from: date
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class GoalStatus:
    goal: Goal
    value: float
    met: bool


@dataclass(frozen=True)
class Meal:
    """Entries eaten close together. The store groups a day's entries into
    meals by time, so nobody has to say which meal an entry belongs to."""

    start: datetime
    entries: tuple[Entry, ...]
    totals: Nutrients


@dataclass(frozen=True)
class DaySummary:
    day: date
    totals: Nutrients
    meals: tuple[Meal, ...]
    goals: tuple[GoalStatus, ...]
    estimated_share: float  # share of the day's kcal that came from estimates, 0..1


@dataclass(frozen=True)
class QuickItem:
    """A one-tap button in the web UI."""

    id: int
    food_id: int
    grams: float
    label: str
    position: int


@dataclass(frozen=True)
class RecipeNutrition:
    """A Tandoor recipe's nutrition for one serving. `complete` is False when
    some ingredient has no nutrient properties or no gram conversion, and
    `missing` names those ingredients."""

    recipe_id: int
    name: str
    servings: float
    per_serving: Nutrients
    complete: bool
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class Workout:
    """A finished session from openGym."""

    day: date
    name: str
    duration_min: float | None = None


@dataclass(frozen=True)
class BodyWeight:
    day: date
    kg: float
