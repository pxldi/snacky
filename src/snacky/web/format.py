"""German number, date and label formatting for the templates."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from snacky.model import Confidence, Entry, GoalKind, GoalStatus, Origin, Source

WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

SOURCE_LABELS = {
    Source.BLS: "BLS",
    Source.OFF: "Open Food Facts",
    Source.LABEL: "Etikett",
    Source.TANDOOR: "Rezept",
    Source.MANUAL: "Manuell",
    Source.AI_ESTIMATE: "Schätzung",
}
CONFIDENCE_LABELS = {Confidence.HIGH: "hoch", Confidence.MEDIUM: "mittel", Confidence.LOW: "niedrig"}
ORIGIN_LABELS = {Origin.CHAT: "Chat", Origin.UI: "Web", Origin.TANDOOR: "Tandoor"}
NUTRIENT_LABELS = {
    "kcal": "Energie",
    "protein_g": "Protein",
    "fat_g": "Fett",
    "carbs_g": "Kohlenhydrate",
    "fibre_g": "Ballaststoffe",
}


def num(value: float | None, digits: int = 0) -> str:
    """1234.5 -> "1.234,5" with `digits` decimals. None becomes a dash."""
    if value is None:
        return "–"
    # Half up like a person rounds, not half to even like Python's format.
    rounded = Decimal(repr(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    text = f"{rounded:,.{digits}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def amount(value: float) -> str:
    """Grams or servings with no trailing zeros: 250 -> "250", 37.5 -> "37,5"."""
    text = f"{value:.1f}"
    return num(float(text), 0 if text.endswith(".0") else 1)


def input_number(value: float) -> str:
    """For an <input>, where the value must use a dot."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def date_long(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day}. {MONTHS[day.month - 1]} {day.year}"


def date_short(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()][:2]}, {day.day}.{day.month}."


def date_range(start: date, end: date) -> str:
    if start.month == end.month and start.year == end.year:
        return f"{start.day}.–{end.day}. {MONTHS[end.month - 1]} {end.year}"
    return f"{start.day}. {MONTHS[start.month - 1]} – {end.day}. {MONTHS[end.month - 1]} {end.year}"


def clock(value: datetime) -> str:
    return value.strftime("%H:%M")


def is_estimate(source: Source, confidence: Confidence | None) -> bool:
    return source is Source.AI_ESTIMATE or (confidence is not None and confidence is not Confidence.HIGH)


def goal_view(status: GoalStatus | None, unit: str) -> dict | None:
    """What the templates need to show one goal: a target text, a 0..1 fill
    and a sentence on how far the day is from it."""
    if status is None:
        return None
    goal, value = status.goal, status.value
    lo, hi = goal.min, goal.max
    if goal.kind is GoalKind.MIN:
        target, short, limit = f"mindestens {num(lo)} {unit}", f"min. {num(lo)}", lo
    elif goal.kind is GoalKind.MAX:
        target, short, limit = f"höchstens {num(hi)} {unit}", f"max. {num(hi)}", hi
    else:
        target, short, limit = f"{num(lo)} bis {num(hi)} {unit}", f"{num(lo)}–{num(hi)}", hi
    if goal.kind is GoalKind.MIN:
        gap = f"noch {num(max(lo - value, 0))} {unit}" if not status.met else "erreicht"
    elif goal.kind is GoalKind.MAX:
        gap = f"noch {num(hi - value)} {unit} frei" if status.met else f"{num(value - hi)} {unit} drüber"
    elif value < lo:
        gap = f"noch {num(lo - value)} {unit} bis zum Ziel"
    elif status.met:
        gap = "im Zielbereich"
    else:
        gap = f"{num(value - hi)} {unit} drüber"
    return {
        "target": target,
        "short": short,
        "gap": gap,
        "met": status.met,
        "fill": min(value / limit, 1.0) if limit else 0.0,
        "limit": limit,
    }


NBSP = "\u00a0"
NO_VALUE = "keine Angabe"


def amount_label(entry: Entry) -> str:
    """ "150 g", "1 Portion" or "2,5 Portionen", with a no-break space so the
    number never wraps away from its unit."""
    if entry.grams:
        return f"{amount(entry.grams)}{NBSP}g"
    if entry.servings:
        unit = "Portion" if entry.servings == 1 else "Portionen"
        return f"{amount(entry.servings)}{NBSP}{unit}"
    return ""


def value_label(value: float | None, unit: str, digits: int = 0) -> str:
    """A nutrient value, or "keine Angabe" when the source does not report it.
    A dash would read as zero."""
    if value is None:
        return NO_VALUE
    return f"{num(value, digits)}{NBSP}{unit}"


def protein_label(entry: Entry) -> str:
    """Protein of one entry. An estimate is whole grams with a leading "≈ ",
    so it does not claim a precision it does not have."""
    protein = entry.nutrients.protein_g
    if is_estimate(entry.source, entry.confidence):
        return f"≈ {num(protein, 0)}{NBSP}g"
    return f"{num(protein, 1)}{NBSP}g"


def protein_estimated_share(entries: list[Entry]) -> float:
    """Share of the protein that comes from estimates, 0..1."""
    total = sum(e.nutrients.protein_g for e in entries)
    if total <= 0:
        return 0.0
    estimated = sum(e.nutrients.protein_g for e in entries if is_estimate(e.source, e.confidence))
    return min(estimated / total, 1.0)


def protein_view(status: GoalStatus | None, *, day: date, today: date, has_entries: bool) -> dict:
    """The protein goal for one day. Keeps every key `goal_view` has, except
    that the sentence `goal_view` calls "gap" is now "gap_text", because "gap"
    is the number of grams still missing."""
    view = goal_view(status, "g") or {}
    view["gap_text"] = view.pop("gap", "")
    lo = status.goal.min if status is not None else None
    eaten = status.value if status is not None else 0.0
    if status is None or lo is None or lo <= 0:
        state, limit, met = "nogoal", None, False
    else:
        limit, met = lo, status.met
        if not has_entries:
            state = "empty"
        elif met:
            state = "met"
        elif day >= today:
            state = "open"
        else:
            state = "missed"
    view.update(
        eaten=eaten,
        limit=limit,
        gap=max(limit - eaten, 0.0) if limit else 0.0,
        over=max(eaten - limit, 0.0) if limit else 0.0,
        fraction=min(eaten / limit, 1.0) if limit else 0.0,
        met=met,
        state=state,
    )
    return view


def gap_closer(quick: list[dict], gap: float) -> None:
    """Marks the one quick item that best closes the protein gap: the smallest
    that reaches it, else the largest. Items start with "closes_gap" False."""
    if not quick:
        return
    reaching = [q for q in quick if q["nutrients"].protein_g >= gap - 1e-9]
    best = (
        min(reaching, key=lambda q: q["nutrients"].protein_g)
        if reaching
        else max(quick, key=lambda q: q["nutrients"].protein_g)
    )
    best["closes_gap"] = True


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def upfirst(text: str) -> str:
    """Upper-case the first letter only; Jinja's capitalize lowercases the rest."""
    return text[:1].upper() + text[1:]
