"""BLS index tests.

The fixture holds 44 real rows of the Bundeslebensmittelschluessel 4.0 (Max
Rubner-Institut, CC BY 4.0, https://blsdb.de), in the original xlsx layout.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from snacky.model import Source
from snacky.sources.bls import _SCHEMA, BlsIndex, build

FIXTURE = Path(__file__).parent / "fixtures" / "bls" / "BLS_4_0_Daten_2025_DE_sample.xlsx"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bls") / "bls.sqlite"
    assert build(FIXTURE, out) == 44
    return out


@pytest.fixture
def index(db):
    idx = BlsIndex(db)
    yield idx
    idx.close()


def names(results):
    return [c.name for c in results]


def test_build_stores_foods_and_extra(db):
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM foods").fetchone() == (44,)
    assert con.execute("SELECT count(*) FROM foods_fts").fetchone() == (44,)
    extra = json.loads(con.execute("SELECT extra FROM foods WHERE code = 'H861000'").fetchone()[0])
    assert extra["CA"] == 185.0
    assert "PROT625" not in extra
    assert con.execute("SELECT unit FROM nutrients WHERE code = 'ENERCC'").fetchone() == ("kcal",)


def test_build_replaces_existing_file(db, tmp_path):
    out = tmp_path / "again.sqlite"
    build(FIXTURE, out)
    assert build(FIXTURE, out) == 44


def test_build_rejects_other_files(tmp_path):
    import zipfile

    bad = tmp_path / "bad.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("nothing", "x")
    with pytest.raises(KeyError):
        build(bad, tmp_path / "out.sqlite")


def test_get(index):
    tofu = index.get("H861000")
    assert tofu.name == "Tofu"
    assert tofu.source is Source.BLS
    assert tofu.source_ref == "H861000"
    assert tofu.per_100g.kcal == 115
    assert tofu.per_100g.protein_g == 15.51
    assert tofu.per_100g.fibre_g == 1.3
    assert tofu.extra["WATER"] == 73.4
    assert index.get("Z000000") is None


def test_tofu_before_dishes(index):
    found = names(index.search("Tofu"))
    assert found[0] == "Tofu"
    dishes = {"Tofu gebraten (mit Fett und Salz)", "Tofu-Bolognese vegan", "Tofu-Burger vegan"}
    plain = [i for i, n in enumerate(found) if n not in dishes]
    assert max(plain) < min(i for i, n in enumerate(found) if n in dishes)


def test_linsen_before_soups(index):
    found = index.search("Linsen", limit=20)
    assert found[0].name == "Linse reif"
    first_dish = min(i for i, c in enumerate(found) if c.source_ref[0] in "XY")
    assert all(c.source_ref[0] not in "XY" for c in found[:first_dish])
    assert {"Linse reif, gekocht", "Linsen-Eintopf mit Suppengemüse"} <= set(names(found))


def test_compound_written_as_one_word(index):
    assert index.search("Haferflocken")[0].name == "Hafer Flocken"


def test_umlauts_fold(index):
    assert index.search("Sojadrink ungesüßt")[0].name == "Sojadrink ungesüßt"
    assert index.search("SOJADRINK UNGESUSST")[0].name == "Sojadrink ungesüßt"  # ss stands for ß
    assert index.search("sojadrink ungesußt")[0].name == "Sojadrink ungesüßt"
    assert index.search("Hahnchen")[0].name.startswith("Hähnchen")
    assert index.search("Hähnchen")[0].name.startswith("Hähnchen")
    assert index.search("Suß")[0].name.startswith("Süß")


def test_prefix_search(index):
    assert "Erdnussmus" in names(index.search("Erdnuss"))
    assert "Sojaproteinisolat" in names(index.search("Sojaprot"))


def test_multiple_words_must_all_match(index):
    found = index.search("Soja Joghurt")
    assert names(found) == ["Soja-Joghurtalternative ungesüßt"]


def test_limit_and_empty_query(index):
    assert len(index.search("Soja", limit=2)) == 2
    assert index.search("") == []
    assert index.search('"*()') == []
    assert index.search("Tofu", limit=0) == []


def test_unknown_word(index):
    assert index.search("Tempeh") == []


def test_opens_read_only(db):
    idx = BlsIndex(db)
    with pytest.raises(sqlite3.OperationalError):
        idx._con.execute("DELETE FROM foods")
    idx.close()


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        BlsIndex(tmp_path / "nope.sqlite")


def mini_index(tmp_path, rows):
    """An index of (code, name) rows with zero nutrients, for ranking tests."""
    out = tmp_path / "mini.sqlite"
    con = sqlite3.connect(out)
    con.executescript(_SCHEMA)
    for code, name in rows:
        con.execute("INSERT INTO foods VALUES (?, ?, 0, 0, 0, 0, NULL, '{}')", (code, name))
        con.execute("INSERT INTO foods_fts (name, code) VALUES (?, ?)", (name, code))
    con.commit()
    con.close()
    return BlsIndex(out)


def test_ascii_spellings_find_umlaut_names(tmp_path):
    idx = mini_index(
        tmp_path,
        [
            ("M111000", "Käse Edamer"),
            ("C111000", "Müsli Basismischung"),
            ("G322100", "Grünkohl roh"),
            ("C222000", "Grieß Weizen"),
        ],
    )
    assert names(idx.search("Kaese")) == ["Käse Edamer"]
    assert names(idx.search("Muesli")) == ["Müsli Basismischung"]
    assert names(idx.search("Gruenkohl")) == ["Grünkohl roh"]
    assert names(idx.search("Griess")) == ["Grieß Weizen"]
    assert names(idx.search("Käse")) == ["Käse Edamer"]


def test_adjective_before_noun(tmp_path):
    idx = mini_index(
        tmp_path,
        [
            ("H725100", "Linse reif"),
            ("H730000", "Linse rot reif"),
            ("H730032", "Linse rot, reif, gekocht"),
            ("X999999", "Rote-Linsensuppe mit Koriander"),
        ],
    )
    assert names(idx.search("rote Linsen"))[:2] == ["Linse rot reif", "Linse rot, reif, gekocht"]


def test_plain_food_before_compounds_and_flour(tmp_path):
    idx = mini_index(
        tmp_path,
        [
            ("W380300", "Kartoffelwurst"),
            ("K280200", "Kartoffelsticks"),
            ("K110100", "Kartoffel geschält, roh"),
            ("C453000", "Reis Mehl"),
            ("C356000", "Reis Grieß"),
            ("C352000", "Reis poliert, roh"),
            ("C559000", "Reisnudeln roh"),
        ],
    )
    assert names(idx.search("Kartoffeln"))[0] == "Kartoffel geschält, roh"
    assert names(idx.search("Reis"))[0] == "Reis poliert, roh"


def test_common_names_map_to_bls_names(tmp_path):
    idx = mini_index(
        tmp_path,
        [
            ("E401000", "Teigwaren eifrei, roh"),
            ("E510000", "Vollkornteigwaren eifrei, roh"),
            ("G312100", "Broccoli roh"),
            ("C351000", "Reis unpoliert, roh"),
            ("C352000", "Reis poliert, roh"),
            ("X720912", "Nudelpudding mit Kochschinken"),
        ],
    )
    assert names(idx.search("Nudeln"))[0] == "Teigwaren eifrei, roh"
    assert names(idx.search("Vollkornnudeln"))[0] == "Vollkornteigwaren eifrei, roh"
    assert names(idx.search("Brokkoli"))[0] == "Broccoli roh"
    assert names(idx.search("Vollkornreis")) == ["Reis unpoliert, roh"]
