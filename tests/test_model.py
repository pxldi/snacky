from snacky.model import Nutrients


def test_for_grams_scales_per_100g():
    tofu = Nutrients(kcal=120, protein_g=15, fat_g=7, carbs_g=2, fibre_g=1)
    got = tofu.for_grams(200)
    assert got.protein_g == 30
    assert got.fibre_g == 2


def test_add_keeps_unknown_fibre_unknown():
    a = Nutrients(100, 10, 1, 1)
    assert (a + a).fibre_g is None
    assert (a + Nutrients(1, 1, 1, 1, 3)).fibre_g == 3
