"""The Bundeslebensmittelschlüssel (BLS 4.0, Max Rubner-Institut, CC BY 4.0).

The raw download is converted once, at image build, into a read-only SQLite
file with a full-text index. At runtime this module only reads that file and
needs nothing beyond the standard library.

Source file
-----------
https://blsdb.de/assets/uploads/BLS_4_0_2025_DE.zip (DOI 10.25826/Data20251217-134202-0)
holds `BLS_4_0_Daten_2025_DE.xlsx`, one sheet, 7,140 food rows below one header
row, 418 columns:

* A `BLS Code`: 7 characters, e.g. `H861000`. The first letter is the main food
  group (B bread, C cereals, F fruit, G vegetables, H pulses/nuts/soy products,
  M dairy, T fish, U/V/W meat and sausage, ...). Groups `X` (1,165 rows) and
  `Y` (885 rows) are composite dishes and recipes. The last digit tells the
  preparation state (0 = as listed, 2 and 3 = cooked variants).
* B `Lebensmittelbezeichnung`: German name. C `Food name`: English name.
* Then 138 nutrients, three columns each: the value, `<CODE> Datenherkunft`
  (origin) and `<CODE> Referenz`. The value header reads
  `<CODE> <German name> [<unit>/100g]`, e.g. `ENERCC Energie (Kilokalorien)
  [kcal/100g]`. All values are per 100 g of edible portion.
* Last column `Hinweis`: free-text remark, ignored here.

Cells hold numbers, or the strings `TR` (trace), `<LOD` and `<LOQ` (below the
detection limit), or `-` (not determined). Trace and below-limit are read as 0.
A `-` in the main five is only expected for fibre and becomes None.

Main values used:

* ENERCC, kcal (calculated from the macros by the BLS formula)
* PROT625, g (nitrogen x 6.25)
* FAT, g
* CHO, g (available carbohydrates, so fibre is not included)
* FIBT, g (total fibre)

Every other numeric nutrient goes into `foods.extra` as JSON keyed by BLS
nutrient code (ENERCJ, WATER, VITC, CA, ...). The `nutrients` table maps each
code to its German name and unit.

The xlsx is read with `zipfile` and `xml.etree`, streamed, so neither the build
nor the tests need a spreadsheet library.

Coverage of vegan staples (protein g per 100 g)
-----------------------------------------------
Tofu H861000 15.51; Seidentofu H861100 4.57; Räuchertofu none (only "Tofu
gebacken" H861062 21.54); Tempeh none; Seitan C558000 "Fleischersatz
glutenhaltig (Seitan)" 28.4; Sojadrink H841100 3.22; Soja-Joghurtalternative
H844000 4.17; Linse reif H725100 23.36 and cooked H730132 9.08 (red: raw
H730000 25.6, cooked H730032 8.8); Kichererbse reif G770400 18.58 and cooked G770432 8.4;
Kidneybohne reif H742100 22.8 and cooked H742132 8.6; Hafer Flocken C133000
13.22; Erdnussmus H110800 29; Sojaproteinisolat H011000 88.3; Erbsenprotein
none; Edamame G750100 13 (raw).

Ranking
-------
X and Y foods are dishes. Codes are not enough on their own ("Hafer Flocken,
gekocht" is a C food), so search sorts by, in order: dish or not, whether the
query starts the name, then name length. A shorter name is a plainer food:
"Tofu" (4 characters) beats "Tofu gebacken", and "Linse reif" beats "Linsensprossen".
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from snacky.model import FoodCandidate, Nutrients, Source

# BLS nutrient codes for the five values every food carries.
_KCAL = "ENERCC"
_PROTEIN = "PROT625"
_FAT = "FAT"
_CARBS = "CHO"
_FIBRE = "FIBT"
_MAIN = (_KCAL, _PROTEIN, _FAT, _CARBS, _FIBRE)

# Main food groups that hold composite dishes and recipes.
_DISH_GROUPS = "XY"

_SCHEMA = """
CREATE TABLE foods (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    carbs_g REAL NOT NULL,
    fibre_g REAL,
    extra TEXT NOT NULL
);
CREATE TABLE nutrients (code TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL);
CREATE VIRTUAL TABLE foods_fts USING fts5(
    name, code UNINDEXED, tokenize = "unicode61 remove_diacritics 2"
);
"""

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_VALUE_HEADER = re.compile(r"^(\S+) (.+) \[(.+?)/100g\]$")
_WORD = re.compile(r"\w+")
# Below the detection limit or a trace amount: nothing worth counting.
_ZERO_MARKS = {"TR", "<LOD", "<LOQ", "<LOD or <LOQ"}


def _fold(text: str) -> str:
    """Lower-case and drop accents like the FTS tokenizer, which keeps ß as it is."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _column_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _read_rows(source: Path):
    """Yield the first sheet's rows as lists of str, float or None."""
    with zipfile.ZipFile(source) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                for _, el in ElementTree.iterparse(f):
                    if el.tag == f"{_NS}si":
                        shared.append("".join(t.text or "" for t in el.iter(f"{_NS}t")))
                        el.clear()
        workbook = ElementTree.fromstring(z.read("xl/workbook.xml"))
        first = workbook.find(f"{_NS}sheets/{_NS}sheet")
        rid = first.get(f"{_REL_NS}id")
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels.iter(f"{_PKG_REL_NS}Relationship") if r.get("Id") == rid)
        path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        with z.open(path) as f:
            for _, el in ElementTree.iterparse(f):
                if el.tag != f"{_NS}row":
                    continue
                row: list[str | float | None] = []
                for c in el.iter(f"{_NS}c"):
                    idx = _column_index(c.get("r", ""))
                    row.extend([None] * (idx - len(row)))
                    kind = c.get("t")
                    if kind == "inlineStr":
                        value: str | float | None = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
                    else:
                        v = c.find(f"{_NS}v")
                        if v is None or v.text is None:
                            value = None
                        elif kind == "s":
                            value = shared[int(v.text)]
                        elif kind in ("str", "e"):
                            value = v.text
                        else:
                            value = float(v.text)
                    row.append(value)
                el.clear()
                yield row


def _number(value: str | float | None) -> float | None:
    if isinstance(value, float):
        return value
    if isinstance(value, str) and value.strip() in _ZERO_MARKS:
        return 0.0
    return None


def build(source: Path, out: Path) -> int:
    """Convert the BLS download at `source` (the .xlsx) into the SQLite file at
    `out`. Returns the number of foods written."""
    rows = _read_rows(Path(source))
    header = next(rows)
    columns: dict[int, tuple[str, str, str]] = {}  # column -> (code, name, unit)
    for i, title in enumerate(header):
        m = _VALUE_HEADER.match(title) if isinstance(title, str) else None
        if m:
            columns[i] = (m.group(1), m.group(2), m.group(3))
    codes = {code for code, _, _ in columns.values()}
    if not {_KCAL, _PROTEIN, _FAT, _CARBS} <= codes:
        raise ValueError("not a BLS 4.0 data file: energy or macro columns are missing")

    out = Path(out)
    out.unlink(missing_ok=True)
    con = sqlite3.connect(out)
    try:
        con.executescript(_SCHEMA)
        con.executemany("INSERT INTO nutrients VALUES (?, ?, ?)", sorted(set(columns.values())))
        count = 0
        for row in rows:
            code, name = row[0], row[1] if len(row) > 1 else None
            if not isinstance(code, str) or not isinstance(name, str):
                continue
            values: dict[str, float | None] = {}
            for i, (nutrient, _, _) in columns.items():
                values[nutrient] = _number(row[i]) if i < len(row) else None
            extra = {k: v for k, v in values.items() if v is not None and k not in _MAIN}
            con.execute(
                "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    name,
                    values[_KCAL] or 0.0,
                    values[_PROTEIN] or 0.0,
                    values[_FAT] or 0.0,
                    values[_CARBS] or 0.0,
                    values.get(_FIBRE),
                    json.dumps(extra, separators=(",", ":")),
                ),
            )
            con.execute("INSERT INTO foods_fts (name, code) VALUES (?, ?)", (name, code))
            count += 1
        con.commit()
    finally:
        con.close()
    return count


def _stem(word: str) -> str:
    """Drop a German plural or case ending so "Linsen" also finds "Linse reif"."""
    for suffix in ("en", "n", "e", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _match_expr(query: str) -> tuple[str, list[str]] | None:
    """An FTS5 expression for the query and the folded spellings a name may start with."""
    tokens = [_fold(t) for t in _WORD.findall(query)]
    if not tokens:
        return None
    parts = []
    for token in tokens:
        options = {f'"{token}"*', f'"{_stem(token)}"*'}
        # BLS writes "Hafer Flocken" where people write "Haferflocken".
        for i in range(4, len(token) - 3):
            options.add(f'("{token[:i]}"* AND "{token[i:]}"*)')
        parts.append("(" + " OR ".join(sorted(options)) + ")")
    starts = {"".join(tokens), "".join(_stem(t) for t in tokens)}
    return " AND ".join(parts), sorted(starts)


def _candidate(row: sqlite3.Row) -> FoodCandidate:
    return FoodCandidate(
        name=row["name"],
        source=Source.BLS,
        per_100g=Nutrients(
            kcal=row["kcal"],
            protein_g=row["protein_g"],
            fat_g=row["fat_g"],
            carbs_g=row["carbs_g"],
            fibre_g=row["fibre_g"],
        ),
        source_ref=row["code"],
        extra=json.loads(row["extra"]),
    )


class BlsIndex:
    def __init__(self, path: str | Path) -> None:
        """Open the converted BLS file read-only."""
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        self._con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._con.row_factory = sqlite3.Row

    def close(self) -> None:
        self._con.close()

    def search(self, query: str, limit: int = 10) -> list[FoodCandidate]:
        """German food names, best match first. Plain foods rank above
        prepared dishes that contain the word."""
        expr = _match_expr(query)
        if expr is None or limit <= 0:
            return []
        match, starts = expr
        try:
            rows = self._con.execute(
                "SELECT f.* FROM foods_fts JOIN foods f ON f.code = foods_fts.code WHERE foods_fts MATCH ?",
                (match,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        def rank(row: sqlite3.Row) -> tuple[int, int, int, str]:
            folded = _fold(row["name"])
            joined = re.sub(r"\W+", "", folded)
            leads = any(joined.startswith(s) for s in starts)
            return (
                row["code"][0] in _DISH_GROUPS,
                not leads,
                len(row["name"]),
                row["code"],
            )

        return [_candidate(r) for r in sorted(rows, key=rank)[:limit]]

    def get(self, code: str) -> FoodCandidate | None:
        """One food by its BLS code."""
        row = self._con.execute("SELECT * FROM foods WHERE code = ?", (code,)).fetchone()
        return None if row is None else _candidate(row)
