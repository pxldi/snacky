"""The lookup order: stored foods, then BLS, then Open Food Facts.

The MCP tools go through here, so a food the assistant names is always
resolved against a database and the numbers never come from the model.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from snacky.model import Food, FoodCandidate, Source
from snacky.sources.bls import BlsIndex
from snacky.sources.off import OffClient, OffUnavailable
from snacky.store import NotFound, Store

# Stored foods are read wider than the caller's limit so that a BLS or OFF hit
# that is already stored is dropped even when its stored copy ranks low.
_STORED_WINDOW = 50


class LookupFailed(Exception):
    """A food or barcode could not be resolved. The message is written for the
    chat model to read."""


@dataclass(frozen=True)
class Match:
    candidate: FoodCandidate
    ref: str  # food:<id>, bls:<code> or off:<barcode>
    food_id: int | None = None  # set when the food is already stored


def _candidate(food: Food) -> FoodCandidate:
    return FoodCandidate(
        name=food.name,
        source=food.source,
        per_100g=food.per_100g,
        source_ref=food.source_ref,
        brand=food.brand,
        servings=food.servings,
        extra=food.extra,
    )


def _stored_match(food: Food) -> Match:
    return Match(candidate=_candidate(food), ref=f"food:{food.id}", food_id=food.id)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _stem(word: str) -> str:
    for suffix in ("en", "n", "e", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def is_good_match(query: str, name: str) -> bool:
    """True when the food's name starts with the query (ignoring case, accents,
    spaces and a German plural ending). A name that only contains the query
    somewhere is a different food, e.g. "Kaffee mit Sojadrink" for "Sojadrink"."""
    words = re.findall(r"\w+", _fold(query))
    if not words:
        return False
    joined = re.sub(r"\W+", "", _fold(name))
    starts = {"".join(words), "".join(_stem(w) for w in words)}
    return any(joined.startswith(s) for s in starts)


class Lookup:
    def __init__(self, store: Store, bls: BlsIndex | None, off: OffClient | None) -> None:
        self.store = store
        self.bls = bls
        self.off = off

    def search_local(self, query: str, limit: int = 5) -> list[Match]:
        """Stored foods, then BLS. Never touches the network."""
        stored = self.store.search_foods(query, _STORED_WINDOW)
        seen = {(f.source, f.source_ref) for f in stored if f.source_ref is not None}
        matches = [_stored_match(f) for f in stored[:limit]]
        if len(matches) < limit and self.bls is not None:
            for candidate in self.bls.search(query, limit):
                if (candidate.source, candidate.source_ref) in seen:
                    continue
                matches.append(Match(candidate=candidate, ref=f"bls:{candidate.source_ref}"))
                if len(matches) >= limit:
                    break
        return matches

    async def search_with_notes(self, query: str, limit: int = 5) -> tuple[list[Match], list[str]]:
        """Like `search`, plus notes for the assistant about what was skipped."""
        matches = self.search_local(query, limit)
        notes: list[str] = []
        if len(matches) < limit and self.off is not None:
            seen = {m.candidate.source_ref for m in matches if m.candidate.source is Source.OFF}
            try:
                found = await self.off.search(query, limit)
            except OffUnavailable as exc:
                notes.append(f"Open Food Facts was skipped: {exc}")
            else:
                stored = self.store.search_foods(query, _STORED_WINDOW)
                seen |= {f.source_ref for f in stored if f.source is Source.OFF}
                for candidate in found:
                    if candidate.source_ref is None or candidate.source_ref in seen:
                        continue
                    matches.append(Match(candidate=candidate, ref=f"off:{candidate.source_ref}"))
                    seen.add(candidate.source_ref)
                    if len(matches) >= limit:
                        break
        return matches, notes

    async def search(self, query: str, limit: int = 5) -> list[Match]:
        """Stored foods first, then BLS, then Open Food Facts only when those
        two give fewer than `limit`. An Open Food Facts outage drops its part."""
        return (await self.search_with_notes(query, limit))[0]

    async def by_ref(self, ref: str) -> Food:
        """Resolve a ref from `search` and store the food, so the next lookup
        finds it locally."""
        kind, _, value = ref.strip().partition(":")
        value = value.strip()
        if not value:
            raise LookupFailed(f"'{ref}' is not a food ref; use one from search_food (food:, bls: or off:).")
        if kind == "food":
            try:
                return self.store.get_food(int(value))
            except ValueError, NotFound:
                raise LookupFailed(f"No stored food {ref}.") from None
        if kind == "bls":
            if self.bls is None:
                raise LookupFailed("The BLS index is not loaded on this server.")
            candidate = self.bls.get(value)
            if candidate is None:
                raise LookupFailed(f"BLS has no food with code {value}.")
            return self.store.upsert_food(candidate)
        if kind == "off":
            food = await self.barcode(value)
            if food is None:
                raise LookupFailed(f"Open Food Facts has no usable product {value}.")
            return food
        raise LookupFailed(f"'{ref}' is not a food ref; use one from search_food (food:, bls: or off:).")

    async def barcode(self, code: str) -> Food | None:
        """The stored food with this barcode (a label reading first, then a
        cached Open Food Facts product), else Open Food Facts, stored."""
        for source in (Source.LABEL, Source.OFF):
            found = self.store.food_by_source_ref(source, code)
            if found is not None:
                return found
        if self.off is None:
            raise LookupFailed("Open Food Facts is not configured on this server.")
        candidate = await self.off.by_barcode(code)
        return None if candidate is None else self.store.upsert_food(candidate)
