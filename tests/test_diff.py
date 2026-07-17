"""Testy diffu mezi uloženým a navrženým rozpisem (úkol 9, viz zadani-faze3-web.md)."""

from solver.schedule import Schedule
from web.diff import sestavit_diff


def _schedule(smeny, jmena=("Alena", "Bedrich")):
    return Schedule(rok=2026, mesic=8, jmena=jmena, smeny=smeny, status="TEST", cas_reseni=0.0)


def test_diff_prazdny_kdyz_beze_zmeny():
    puvodni = _schedule({("Alena", 1): "D"})
    novy = _schedule({("Alena", 1): "D"})
    assert sestavit_diff(puvodni, novy) == []


def test_diff_obsahuje_zmenu_smeny():
    puvodni = _schedule({("Alena", 1): "D"})
    novy = _schedule({("Alena", 1): "N"})

    diff = sestavit_diff(puvodni, novy)
    assert len(diff) == 1
    assert diff[0].jmeno == "Alena"
    assert diff[0].den == 1
    assert diff[0].bylo == "Denní"
    assert diff[0].bude == "Noční"


def test_diff_zmena_z_volna_na_smenu():
    puvodni = _schedule({})
    novy = _schedule({("Alena", 1): "D"})

    diff = sestavit_diff(puvodni, novy)
    assert diff[0].bylo == "volno"
    assert diff[0].bude == "Denní"


def test_diff_zmena_ze_smeny_na_volno():
    puvodni = _schedule({("Alena", 1): "D"})
    novy = _schedule({})

    diff = sestavit_diff(puvodni, novy)
    assert diff[0].bylo == "Denní"
    assert diff[0].bude == "volno"


def test_diff_neobsahuje_nezmenene_dny():
    puvodni = _schedule({("Alena", 1): "D", ("Alena", 2): "N"})
    novy = _schedule({("Alena", 1): "D", ("Alena", 2): "D"})

    diff = sestavit_diff(puvodni, novy)
    assert len(diff) == 1
    assert diff[0].den == 2


def test_diff_je_chronologicky_a_po_zamestnancich_abecedne():
    puvodni = _schedule({})
    novy = _schedule({("Bedrich", 5): "D", ("Alena", 3): "N", ("Alena", 1): "D"})

    diff = sestavit_diff(puvodni, novy)
    poradi = [(r.jmeno, r.den) for r in diff]
    assert poradi == [("Alena", 1), ("Alena", 3), ("Bedrich", 5)]


def test_diff_den_tydne_odpovida_datu():
    puvodni = _schedule({})
    novy = _schedule({("Alena", 1): "D"})  # 1.8.2026 je sobota

    diff = sestavit_diff(puvodni, novy)
    assert diff[0].den_tydne == "So"
