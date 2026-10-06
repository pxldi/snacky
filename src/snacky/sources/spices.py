"""Nutrients for herbs, spices, salt and water, which BLS 4.0 does not list.

BLS has no ground cumin, turmeric, oregano, thyme, bay leaf, paprika powder or
chilli flakes, yet recipes name them in nearly every dish. Without values a
recipe stays incomplete however small the amount, so these come from USDA
FoodData Central (SR Legacy, public domain), one entry per FDC id.

FDC reports carbohydrate "by difference", which includes fibre. BLS and the
rest of Snacky count available carbohydrate, so fibre is subtracted here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from snacky.model import FoodCandidate, Nutrients, Source

_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class _Spice:
    name: str
    fdc_id: int | None  # None for salt and water, which carry no energy
    kcal: float
    protein_g: float
    fat_g: float
    carbs_total_g: float
    fibre_g: float
    aliases: tuple[str, ...]


# Values per 100 g from the FDC SR Legacy entry named by fdc_id.
_SPICES = (
    _Spice("Kreuzkümmel", 170923, 375, 17.81, 22.27, 44.24, 10.5, ("kreuzkummel", "cumin")),
    _Spice("Kurkuma", 172231, 312, 9.68, 3.25, 67.14, 22.7, ("kurkuma", "turmeric", "gelbwurz")),
    _Spice("Oregano getrocknet", 171328, 265, 9.0, 4.28, 68.92, 42.5, ("oregano",)),
    _Spice("Thymian getrocknet", 170938, 276, 9.11, 7.43, 63.94, 37.0, ("thymian", "thyme")),
    _Spice("Thymian frisch", 173470, 101, 5.56, 1.68, 24.45, 14.0, ("thymian", "thyme")),
    _Spice("Majoran getrocknet", 170928, 271, 12.66, 7.04, 60.56, 40.3, ("majoran", "marjoram")),
    _Spice(
        "Lorbeerblatt", 170917, 313, 7.61, 8.36, 74.97, 26.3, ("lorbeer", "lorbeerblatt", "lorbeerblatter")
    ),
    _Spice("Paprikapulver", 171329, 282, 14.14, 12.89, 53.99, 34.9, ("paprikapulver",)),
    _Spice(
        "Chiliflocken/Cayennepfeffer",
        170932,
        318,
        12.01,
        17.27,
        56.63,
        27.2,
        ("chiliflocken", "chilipulver", "cayennepfeffer", "cayenne"),
    ),
    _Spice("Zimt gemahlen", 171320, 247, 3.99, 1.24, 80.59, 53.1, ("zimt", "cinnamon")),
    _Spice("Muskatnuss gemahlen", 171326, 525, 5.84, 36.31, 49.29, 20.8, ("muskat", "muskatnuss", "nutmeg")),
    _Spice("Koriander gemahlen", 170922, 298, 12.37, 17.77, 54.99, 41.9, ("koriander", "koriandersamen")),
    _Spice(
        "Koriandergrün frisch", 169997, 23, 2.13, 0.52, 3.67, 2.8, ("koriander", "koriandergrun", "cilantro")
    ),
    _Spice("Kümmel", 170919, 333, 19.77, 14.59, 49.9, 38.0, ("kummel", "caraway")),
    _Spice("Dill frisch", 172233, 43, 3.46, 1.12, 7.02, 2.1, ("dill",)),
    _Spice("Salz", None, 0, 0, 0, 0, 0, ("salz", "speisesalz", "meersalz", "salt")),
    _Spice("Wasser", None, 0, 0, 0, 0, 0, ("wasser", "water")),
)

# Words that describe the form, not the food. "Kreuzkümmel gemahlen" is cumin.
_FORM_WORDS = {
    "gemahlen",
    "gemahlene",
    "gemahlener",
    "getrocknet",
    "getrocknete",
    "getrockneter",
    "frisch",
    "frische",
    "frischer",
    "frisches",
    "edelsuß",
    "edelsuss",
    "rosenscharf",
    "geraucht",
    "gerauchert",
    "gerauchertes",
    "scharf",
    "suß",
    "ground",
    "dried",
    "fresh",
    "table",
    "kalt",
    "warm",
    "fein",
    "grob",
    "jodiert",
    "iodiert",
    "und",
    "pfeffer",
}
_FRESH = {"frisch", "frische", "frischer", "frisches", "fresh"}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def search(query: str, limit: int = 3) -> list[FoodCandidate]:
    """Entries whose name is the query once form words are dropped. A plain
    name may fit two forms (dried or fresh thyme); the one the query's form
    words point to comes first, dried otherwise, since recipes measure dried
    herbs by the spoon."""
    words = _WORD.findall(_fold(query))
    # "Salz und Pfeffer" keeps only "salz", which is right for a seasoning line.
    core = {w for w in words if w not in _FORM_WORDS}
    if len(core) != 1:
        return []
    (key,) = core
    found = [s for s in _SPICES if key in s.aliases]
    fresh = any(w in _FRESH for w in words)
    found.sort(key=lambda s: ("frisch" in s.name) != fresh)
    return [_candidate(s) for s in found[:limit]]


def _candidate(s: _Spice) -> FoodCandidate:
    return FoodCandidate(
        name=s.name,
        source=Source.MANUAL,
        per_100g=Nutrients(
            kcal=s.kcal,
            protein_g=s.protein_g,
            fat_g=s.fat_g,
            carbs_g=round(s.carbs_total_g - s.fibre_g, 2),
            fibre_g=s.fibre_g,
        ),
        source_ref=f"FDC {s.fdc_id}" if s.fdc_id else "none",
    )
