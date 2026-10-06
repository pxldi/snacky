from snacky.model import Source
from snacky.sources import spices


def names(query):
    return [c.name for c in spices.search(query)]


def test_recipe_names_find_the_spice():
    assert names("Kreuzkümmel gemahlen") == ["Kreuzkümmel"]
    assert names("ground cumin") == ["Kreuzkümmel"]
    assert names("Kurkuma") == ["Kurkuma"]
    assert names("Oregano, getrocknet") == ["Oregano getrocknet"]
    assert names("Paprikapulver geräuchert") == ["Paprikapulver"]
    assert names("Lorbeerblatt") == ["Lorbeerblatt"]
    assert names("Salz und Pfeffer") == ["Salz"]
    assert names("Wasser, kalt") == ["Wasser"]


def test_form_words_pick_fresh_or_dried():
    assert names("Thymian") == ["Thymian getrocknet", "Thymian frisch"]
    assert names("frischer Thymian") == ["Thymian frisch", "Thymian getrocknet"]
    assert names("Koriander gemahlen")[0] == "Koriander gemahlen"
    assert names("frischer Koriander")[0] == "Koriandergrün frisch"


def test_other_foods_are_left_to_bls():
    assert names("Paprika") == []
    assert names("rote Zwiebel") == []
    assert names("schwarzer Pfeffer aus der Mühle") == []


def test_carbs_exclude_fibre_like_bls():
    (cumin,) = spices.search("Kreuzkümmel")
    assert cumin.source is Source.MANUAL and cumin.source_ref == "FDC 170923"
    n = cumin.per_100g
    assert (n.kcal, n.protein_g, n.fat_g, n.carbs_g, n.fibre_g) == (375, 17.81, 22.27, 33.74, 10.5)
    (salt,) = spices.search("Salz")
    assert salt.source_ref == "none" and salt.per_100g.kcal == 0
