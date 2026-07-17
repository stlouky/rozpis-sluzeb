"""Testy mřížky měsíce (úkol 3, viz zadani-faze3-web.md)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from solver.schedule import Schedule
from web.app import app
from web.mrizka import sestavit_mrizku


@pytest.fixture
def conn():
    connection = repo.pripojit(":memory:")
    repo.inicializovat_schema(connection)
    yield connection
    connection.close()


def _ulozit_zakladni_rozpis(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    id_bedrich = repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
        smeny={("Alena", 1): "D", ("Bedřich", 1): "N", ("Bedřich", 2): "N"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    return id_alena, id_bedrich


# --- web/mrizka.py: sestavit_mrizku přímo, bez HTTP ---

def test_sestavit_mrizku_radky_jsou_abecedne_a_obsahuji_smeny(conn):
    _ulozit_zakladni_rozpis(conn)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)

    assert [r.jmeno for r in mrizka.radky] == ["Alena", "Bedřich"]
    alena = mrizka.radky[0]
    assert alena.bunky[0].smena == "D"  # 1.8.
    assert alena.bunky[1].smena is None  # 2.8. - volno
    bedrich = mrizka.radky[1]
    assert bedrich.bunky[0].smena == "N"
    assert bedrich.pocet_n == 2
    assert bedrich.pocet_d == 0


def test_sestavit_mrizku_obsazeni_je_pocet_d_n_za_den(conn):
    _ulozit_zakladni_rozpis(conn)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)

    # 1.8.: Alena D, Bedřich N -> (1, 1); 2.8.: jen Bedřich N -> (0, 1);
    # 3.8.: nikdo -> (0, 0)
    assert mrizka.obsazeni[0] == (1, 1)
    assert mrizka.obsazeni[1] == (0, 1)
    assert mrizka.obsazeni[2] == (0, 0)
    assert len(mrizka.obsazeni) == mrizka.dny[-1]  # jeden záznam na každý den měsíce


def test_sestavit_mrizku_souhrn_pocita_d_n_vikend(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    # 1.8.2026 je sobota (víkend) - D tuhle sobotu, N v pondělí (ne víkend)
    schedule = Schedule(rok=2026, mesic=8, jmena=("Alena",),
                         smeny={("Alena", 1): "D", ("Alena", 3): "N"},
                         status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    radek = mrizka.radky[0]
    assert radek.pocet_d == 1
    assert radek.pocet_n == 1
    assert radek.pocet_vikendu == 1  # jen 1.8. (sobota) se počítá


def test_sestavit_mrizku_dov_a_jina_nedostupnost_se_lisi(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 3), "DOV")
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 4), date(2026, 8, 4), "NEM")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    radek = mrizka.radky[0]
    bunka_dov = radek.bunky[2]  # 3.8. (0-indexováno)
    bunka_nem = radek.bunky[3]  # 4.8.

    assert bunka_dov.nedostupnost == "DOV"
    assert bunka_dov.trida == "nedostupnost-dov"
    assert bunka_dov.text == ""  # DOV se jen barví, bez textu (jako v PDF)

    assert bunka_nem.nedostupnost == "NEM"
    assert bunka_nem.trida == "nedostupnost-jina"
    assert bunka_nem.text == "NEM"  # ostatní nedostupnosti = text typu


def test_sestavit_mrizku_pozadavek_se_zkrati_na_poz(conn):
    # POZADAVEK je jediný typ delší než 3 znaky - v buňce by přetékal a
    # překrýval sousední (viz nález), musí se zkrátit stejně jako v legendě
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "POZADAVEK")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    bunka = mrizka.radky[0].bunky[4]  # 5.8.

    assert bunka.nedostupnost == "POZADAVEK"
    assert bunka.text == "POZ"
    assert bunka.nazev_nedostupnosti == "Požadavek"


def test_sestavit_mrizku_poznamka_jen_kdyz_je_admin(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 3), date(2026, 8, 3), "OST", poznamka="soukromý důvod"
    )

    mrizka_admin = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka_admin.radky[0].bunky[2].poznamka == "soukromý důvod"

    mrizka_nahled = sestavit_mrizku(conn, 2026, 8, je_admin=False)
    assert mrizka_nahled.radky[0].bunky[2].poznamka is None
    assert mrizka_nahled.radky[0].bunky[2].nedostupnost == "OST"  # typ ano, poznámka ne


def test_sestavit_mrizku_vikendy_odpovidaji_dnum(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    # srpen 2026: 1. a 2. je So/Ne
    assert mrizka.vikendy[0] is True
    assert mrizka.vikendy[1] is True
    assert mrizka.vikendy[2] is False
    assert mrizka.dny_tydne[0] == "So"


# --- HTTP vrstva: role a měsíc (viz zadani-faze3-web.md, úkol 3) ---

@pytest.fixture
def klient(tmp_path):
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 3), date(2026, 8, 3), "OST", poznamka="tajna-poznamka-xyz"
    )
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 12), date(2026, 8, 12), "POZADAVEK")
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    with TestClient(app, base_url="https://testserver") as klient:
        yield klient


def _prihlasit(klient, jmeno, heslo):
    klient.post("/login", data={"jmeno": jmeno, "heslo": heslo})


def test_korenova_stranka_presmeruje_na_rozpis(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/", follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/rozpis"


def test_admin_muze_zobrazit_libovolny_mesic(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2020-01")
    assert odpoved.status_code == 200
    assert "01/2020" in odpoved.text


def test_nahled_ignoruje_parametr_mesic_a_vidi_jen_aktualni(klient, monkeypatch):
    import web.app as app_modul

    class _Dnes(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 15)

    monkeypatch.setattr(app_modul, "date", _Dnes)

    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved = klient.get("/rozpis?mesic=2020-01")
    assert odpoved.status_code == 200
    assert "08/2026" in odpoved.text
    assert "01/2020" not in odpoved.text


def test_nahled_nevidi_poznamku_admin_ano(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved_admin = klient.get("/rozpis?mesic=2026-08")
    assert "tajna-poznamka-xyz" in odpoved_admin.text

    klient.post("/logout")
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved_nahled = klient.get("/rozpis")
    assert "tajna-poznamka-xyz" not in odpoved_nahled.text


def test_nahled_nema_navigaci_na_jiny_mesic(klient):
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved = klient.get("/rozpis")
    assert "předchozí" not in odpoved.text
    assert "další" not in odpoved.text


def test_admin_ma_navigaci_na_jiny_mesic(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis")
    assert "předchozí" in odpoved.text
    assert "další" in odpoved.text


def test_rozpis_zkracuje_pozadavek_na_poz(klient):
    # nález: POZADAVEK se dřív vypisoval celý a přetékal mimo buňku
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert ">POZ<" in odpoved.text
    assert "POZADAVEK" not in odpoved.text
    assert 'title="Požadavek"' in odpoved.text


def test_rozpis_zobrazuje_radek_obsazeni(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert "Obsazení" in odpoved.text


def test_rozpis_bez_loginu_presmeruje_na_login(klient):
    odpoved = klient.get("/rozpis", follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/login"
