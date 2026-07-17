"""Testy parsování importních textových souborů (db/import_txt.py).

Reálné zamestnanci.txt/pozadavky.txt jsou gitignorované a obsahují reálná
jména - formát byl z nich odvozen, ale testy používají VLASTNÍ fiktivní
data (tests/fixtures/import_txt/), nikdy reálná (viz CLAUDE.md,
bezpečnostní invarianty).
"""

from datetime import date

import pytest

from db.import_txt import (
    RadekPozadavku,
    je_konec_pomeru,
    najit_zamestnance,
    parsovat_datum,
    parsovat_radek_pozadavku,
    parsovat_rozsah,
    rozpoznat_typ,
)
from db.models import Zamestnanec


def test_parsovat_datum_jednoduchy_format():
    assert parsovat_datum("5.3", 2026) == date(2026, 3, 5)
    assert parsovat_datum(" 21.8 ", 2026) == date(2026, 8, 21)


def test_parsovat_datum_neplatny_format_vyhodi_value_error():
    with pytest.raises(ValueError):
        parsovat_datum("nesmysl", 2026)


@pytest.mark.parametrize(
    "text,ocekavano",
    [
        ("21.8", (date(2026, 8, 21), date(2026, 8, 21))),
        ("1.8 - 31.8", (date(2026, 8, 1), date(2026, 8, 31))),
        ("1.8-2.8", (date(2026, 8, 1), date(2026, 8, 2))),
        ("8.8 -16.8", (date(2026, 8, 8), date(2026, 8, 16))),
        ("9.8 - 23.8", (date(2026, 8, 9), date(2026, 8, 23))),
    ],
)
def test_parsovat_rozsah_ruzne_mezery_kolem_pomlcky(text, ocekavano):
    # reálný soubor má nekonzistentní mezery kolem pomlčky u rozsahů -
    # tenhle test ověřuje, že parser to zvládne všechny varianty
    assert parsovat_rozsah(text, 2026) == ocekavano


@pytest.mark.parametrize(
    "popis,ocekavany_typ,ocekavana_zakazana_smena",
    [
        ("dovolená", "DOV", None),
        ("volno", "OST", None),
        ("lékař", "OST", None),
        ("ne denní směnu", "POZADAVEK", "D"),
        ("ne noční směnu", "POZADAVEK", "N"),
        ("ne noční", "POZADAVEK", "N"),
    ],
)
def test_rozpoznat_typ_zname_popisy(popis, ocekavany_typ, ocekavana_zakazana_smena):
    assert rozpoznat_typ(popis) == (ocekavany_typ, ocekavana_zakazana_smena)


def test_rozpoznat_typ_neznamy_popis_vraci_none():
    assert rozpoznat_typ("nějaký exotický důvod") is None


@pytest.mark.parametrize(
    "popis",
    [
        "končí (ve zkušební době)",
        "končí",
        "skončí ve zkušební době",
        "ukončení pracovního poměru",
        "odchod",
        "odchází k tomuto dni",
    ],
)
def test_je_konec_pomeru_rozpozna_konec_pracovniho_pomeru(popis):
    assert je_konec_pomeru(popis) is True


@pytest.mark.parametrize("popis", ["dovolená", "volno", "lékař", "ne noční směnu"])
def test_je_konec_pomeru_nereaguje_na_bezne_nedostupnosti(popis):
    assert je_konec_pomeru(popis) is False


def test_parsovat_radek_pozadavku_bez_mezery_za_carkou():
    # reálný soubor: "3.8, Adamcová Bezemková,volno" - bez mezery po druhé čárce
    radek = parsovat_radek_pozadavku(1, "3.8, Testovská,volno", 2026)
    assert radek == RadekPozadavku(
        cislo_radku=1, od=date(2026, 8, 3), do=date(2026, 8, 3),
        jmeno="Testovská", popis="volno",
    )


def test_parsovat_radek_pozadavku_malo_casti_vyhodi_chybu():
    with pytest.raises(ValueError, match="řádek 3"):
        parsovat_radek_pozadavku(3, "jen dve casti", 2026)


def test_parsovat_radek_pozadavku_spatne_datum_vyhodi_chybu_s_cislem_radku():
    with pytest.raises(ValueError, match="řádek 5"):
        parsovat_radek_pozadavku(5, "nesmysl, Testovská, volno", 2026)


def _z(id_, jmeno):
    return Zamestnanec(id=id_, jmeno=jmeno, aktivni_od=date(2020, 1, 1), aktivni_do=None, stitky="")


def test_najit_zamestnance_presna_shoda():
    zamestnanci = [_z(1, "Testovská Anna"), _z(2, "Ukázka Cyril")]
    assert najit_zamestnance(zamestnanci, "Testovská Anna") == zamestnanci[0]


def test_najit_zamestnance_prefix_prijmeni():
    zamestnanci = [_z(1, "Testovská Anna"), _z(2, "Vzorková Bedřiška Karolína")]
    assert najit_zamestnance(zamestnanci, "Testovská") == zamestnanci[0]
    assert najit_zamestnance(zamestnanci, "Vzorková Bedřiška") == zamestnanci[1]


def test_najit_zamestnance_neexistujici_vraci_none():
    zamestnanci = [_z(1, "Testovská Anna")]
    assert najit_zamestnance(zamestnanci, "Neznámá Osoba") is None


def test_najit_zamestnance_nejednoznacny_prefix_vraci_none():
    # "Nová" by nejednoznačně sedělo na oba - radši nehádat (viz db/cli.py)
    zamestnanci = [_z(1, "Nová Alena"), _z(2, "Nová Bedřiška")]
    assert najit_zamestnance(zamestnanci, "Nová") is None
