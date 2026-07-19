"""Testy stránky /pozadavky - samoobslužné podávání požadavků (úkol 9b,
viz zadani-faze3-web.md)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from web import auth as web_auth
from web.app import app


@pytest.fixture
def klient(tmp_path):
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    web_auth._NEUSPESNE_POKUSY.clear()
    web_auth._ZABLOKOVANO_DO.clear()

    with TestClient(app, base_url="https://testserver") as klient:
        klient.post("/login", data={"jmeno": "admin", "heslo": "tajneheslo"})
        klient.id_alena = id_alena
        yield klient


@pytest.fixture
def klient_nahled(klient):
    klient.post("/logout")
    klient.post("/login", data={"jmeno": "nahled", "heslo": "tajneheslo2"})
    return klient


def _conn(klient):
    return repo.pripojit(klient.app.state.cesta_db)


def _pozadavek_data(klient, popis="volno na svatbu"):
    return {
        "zamestnanec_id": klient.id_alena,
        "od": "2026-08-03",
        "do": "2026-08-04",
        "popis": popis,
    }


# --- podání požadavku (obě role) ---

def test_admin_smi_podat_pozadavek(klient):
    odpoved = klient.post("/pozadavky", data=_pozadavek_data(klient))
    assert odpoved.status_code == 200

    pozadavky = repo.vsechny_nedostupnosti(_conn(klient))
    assert len(pozadavky) == 1
    assert pozadavky[0].stav == "podano"
    assert pozadavky[0].poznamka == "volno na svatbu"


def test_nahled_smi_podat_pozadavek(klient_nahled):
    odpoved = klient_nahled.post("/pozadavky", data=_pozadavek_data(klient_nahled))
    assert odpoved.status_code == 200
    assert len(repo.vsechny_nedostupnosti(_conn(klient_nahled))) == 1


def test_podani_pozadavku_neexistujiciho_zamestnance_404(klient):
    data = _pozadavek_data(klient)
    data["zamestnanec_id"] = klient.id_alena + 999
    odpoved = klient.post("/pozadavky", data=data)
    assert odpoved.status_code == 404


def test_podani_pozadavku_se_skutecnym_typem(klient):
    # úkol 9d: self-service smí zakládat skutečné typy (NEM/DOV/...), ne
    # jen obecný POZADAVEK.
    data = _pozadavek_data(klient)
    data["typ"] = "NEM"
    odpoved = klient.post("/pozadavky", data=data)
    assert odpoved.status_code == 200

    pozadavky = repo.vsechny_nedostupnosti(_conn(klient))
    assert pozadavky[0].typ == "NEM"
    assert pozadavky[0].stav == "podano"


def test_podani_pozadavku_neaktivniho_zamestnance_vrati_chybu(klient):
    conn = _conn(klient)
    repo.deaktivovat_zamestnance(conn, klient.id_alena, date(2026, 7, 1))
    conn.close()

    odpoved = klient.post("/pozadavky", data=_pozadavek_data(klient))
    assert odpoved.status_code == 400
    assert "aktivní" in odpoved.text


# --- výpis (obě role) ---

def test_seznam_pozadavku_ukazuje_stav(klient):
    klient.post("/pozadavky", data=_pozadavek_data(klient))
    odpoved = klient.get("/pozadavky")
    assert odpoved.status_code == 200
    assert "Alena" in odpoved.text
    assert "Čeká na schválení" in odpoved.text


def test_nahled_vidi_popis_pozadavku(klient_nahled):
    # výjimka ze zabezpečení č.4 (viz zadani-faze3-web.md úkol 9b) -
    # nahled musí vidět popis VŠECH požadavků, ne jen svých (sdílený
    # účet nemá per-osobu identitu, jinak by nešlo zjistit stav).
    klient_nahled.post("/pozadavky", data=_pozadavek_data(klient_nahled, popis="tajny popis"))
    odpoved = klient_nahled.get("/pozadavky")
    assert "tajny popis" in odpoved.text


# --- schválení/zamítnutí (jen admin) ---

def test_nahled_dostane_403_na_schvalit_a_zamitnout(klient_nahled):
    poz_id = repo.pridat_pozadavek(
        _conn(klient_nahled), klient_nahled.id_alena, date(2026, 8, 3), date(2026, 8, 4), "x"
    )
    assert klient_nahled.post(f"/pozadavky/{poz_id}/schvalit").status_code == 403
    assert klient_nahled.post(f"/pozadavky/{poz_id}/zamitnout").status_code == 403


def test_admin_smi_schvalit_pozadavek(klient):
    conn = _conn(klient)
    poz_id = repo.pridat_pozadavek(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 4), "x")
    conn.close()

    odpoved = klient.post(f"/pozadavky/{poz_id}/schvalit")
    assert odpoved.status_code == 200
    assert repo.nedostupnost_podle_id(_conn(klient), poz_id).stav == "schvaleno"


def test_admin_smi_zamitnout_pozadavek(klient):
    # Zamítnutí záznam rovnou maže (žádný audit trail stavu 'zamitnuto').
    conn = _conn(klient)
    poz_id = repo.pridat_pozadavek(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 4), "x")
    conn.close()

    odpoved = klient.post(f"/pozadavky/{poz_id}/zamitnout")
    assert odpoved.status_code == 200
    assert repo.nedostupnost_podle_id(_conn(klient), poz_id) is None


def test_schvalit_neexistujiciho_pozadavku_404(klient):
    assert klient.post("/pozadavky/999/schvalit").status_code == 404


def test_schvalit_uz_vyrizeneho_pozadavku_404(klient):
    # úkol 9d: guard kontroluje stav='podano', ne typ - jednou vyřízené
    # (nebo běžný admin záznam, co nikdy 'podano' nebylo) se přes tuhle
    # routu znovu sáhnout nedá.
    conn = _conn(klient)
    poz_id = repo.pridat_pozadavek(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 4), "x")
    repo.schvalit_pozadavek(conn, poz_id)
    conn.close()

    assert klient.post(f"/pozadavky/{poz_id}/schvalit").status_code == 404
    assert klient.post(f"/pozadavky/{poz_id}/zamitnout").status_code == 404


def test_schvalit_beznou_admin_nedostupnost_404(klient):
    conn = _conn(klient)
    ned_id = repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 4), "DOV")
    conn.close()

    assert klient.post(f"/pozadavky/{ned_id}/schvalit").status_code == 404


# --- navrat (úkol 9d: widgety na /rozpis, ne na samostatné stránce) ---

def test_podani_pozadavku_se_vraci_na_navrat(klient):
    data = _pozadavek_data(klient)
    data["navrat"] = "/rozpis?mesic=2026-08"
    odpoved = klient.post("/pozadavky", data=data, follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/rozpis?mesic=2026-08"


def test_podani_pozadavku_bez_navrat_jde_na_pozadavky(klient):
    odpoved = klient.post("/pozadavky", data=_pozadavek_data(klient), follow_redirects=False)
    assert odpoved.headers["location"] == "/pozadavky"


def test_podani_pozadavku_odmitne_cizi_navrat(klient):
    # ochrana proti open-redirectu - "//" je protokol-relativní adresa,
    # mohla by vést mimo appku, i když vypadá jako cesta.
    data = _pozadavek_data(klient)
    data["navrat"] = "//zlyweb.example/phishing"
    odpoved = klient.post("/pozadavky", data=data, follow_redirects=False)
    assert odpoved.headers["location"] == "/pozadavky"


def test_schvalit_pozadavek_se_vraci_na_navrat(klient):
    conn = _conn(klient)
    poz_id = repo.pridat_pozadavek(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 4), "x")
    conn.close()

    odpoved = klient.post(
        f"/pozadavky/{poz_id}/schvalit",
        data={"navrat": "/rozpis?mesic=2026-08"},
        follow_redirects=False,
    )
    assert odpoved.headers["location"] == "/rozpis?mesic=2026-08"


# --- hromadné schválení nekonfliktních (úkol 9d) ---

def test_schvalit_nekonfliktni_z_widgetu(klient):
    conn = _conn(klient)
    poz_id = repo.pridat_pozadavek(conn, klient.id_alena, date(2026, 8, 5), date(2026, 8, 5), "x")
    conn.close()

    odpoved = klient.post(
        "/rozpis/pozadavky/schvalit-nekonfliktni",
        data={"mesic": "2026-08"},
        follow_redirects=False,
    )
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/rozpis?mesic=2026-08"
    assert repo.nedostupnost_podle_id(_conn(klient), poz_id).stav == "schvaleno"


def test_schvalit_nekonfliktni_dostane_403_pro_nahled(klient_nahled):
    odpoved = klient_nahled.post(
        "/rozpis/pozadavky/schvalit-nekonfliktni", data={"mesic": "2026-08"}
    )
    assert odpoved.status_code == 403
