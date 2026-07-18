"""Testy hashování/ověřování hesel (db/auth.py)."""

from db.auth import hashovat_heslo, overit_heslo


def test_hashovat_a_overit_heslo_spravne():
    heslo_hash = hashovat_heslo("tajneheslo")
    assert overit_heslo("tajneheslo", heslo_hash) is True


def test_overit_heslo_spatne_heslo():
    heslo_hash = hashovat_heslo("tajneheslo")
    assert overit_heslo("jine_heslo", heslo_hash) is False


def test_overit_heslo_prilis_dlouhe_heslo_nevyhodi_vyjimku():
    # bcrypt >=4.1 na heslo delší než 72 bajtů vyhazuje ValueError místo
    # tichého oříznutí - bez ošetření by nepřihlášený uživatel dlouhým
    # heslem na /login shodil endpoint na HTTP 500 (nález auditu appky).
    heslo_hash = hashovat_heslo("tajneheslo")
    assert overit_heslo("x" * 100, heslo_hash) is False
