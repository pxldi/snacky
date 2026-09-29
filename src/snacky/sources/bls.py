"""The Bundeslebensmittelschlüssel (BLS 4.0, Max Rubner-Institut, CC BY 4.0).

The raw download is converted once, at image build, into a read-only SQLite
file with a full-text index. At runtime this module only reads that file.
"""

from __future__ import annotations

from pathlib import Path

from snacky.model import FoodCandidate


class BlsIndex:
    def __init__(self, path: str | Path) -> None:
        """Open the converted BLS file read-only."""
        raise NotImplementedError

    def search(self, query: str, limit: int = 10) -> list[FoodCandidate]:
        """German food names, best match first. Plain foods rank above
        prepared dishes that contain the word."""
        raise NotImplementedError

    def get(self, code: str) -> FoodCandidate | None:
        """One food by its BLS code."""
        raise NotImplementedError


def build(source: Path, out: Path) -> int:
    """Convert the BLS download at `source` into the SQLite file at `out`.
    Returns the number of foods written."""
    raise NotImplementedError
