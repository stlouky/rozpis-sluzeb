"""Testy webové kostry a přihlášení (úkol 1, viz zadani-faze3-web.md)."""

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from web.app import app


@pytest.fixture
def klient(tmp_path):
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    conn.close()

    # base_url na https, ať se v testu reálně uplatní Secure cookie flag
    # (viz CLAUDE.md, bezpečnostní invarianty).
    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    with TestClient(app, base_url="https://testserver") as klient:
        yield klient


def _prihlasit(klient, jmeno, heslo):
    return klient.post("/login", data={"jmeno": jmeno, "heslo": heslo})


def test_bez_loginu_presmeruje_na_login(klient):
    odpoved = klient.get("/", follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/login"


def test_login_stranka_je_verejna(klient):
    odpoved = klient.get("/login")
    assert odpoved.status_code == 200
    assert "Přihlásit" in odpoved.text


def test_spravne_prihlaseni_nastavi_cookie_a_pusti_na_domovskou(klient):
    odpoved = _prihlasit(klient, "admin", "tajneheslo")
    assert odpoved.status_code == 200  # TestClient defaultně následuje redirect
    assert "session" in klient.cookies
    assert "admin" in odpoved.text


def test_spravne_prihlaseni_cookie_je_httponly_secure_samesite_lax(klient):
    odpoved = klient.post(
        "/login", data={"jmeno": "admin", "heslo": "tajneheslo"}, follow_redirects=False
    )
    nastaveni_cookie = odpoved.headers["set-cookie"]
    assert "httponly" in nastaveni_cookie.lower()
    assert "secure" in nastaveni_cookie.lower()
    assert "samesite=lax" in nastaveni_cookie.lower()


def test_spatne_heslo_odmitne_a_nenastavi_cookie(klient):
    odpoved = _prihlasit(klient, "admin", "spatne-heslo")
    assert odpoved.status_code == 401
    assert "session" not in klient.cookies


def test_neexistujici_uzivatel_odmitne(klient):
    odpoved = _prihlasit(klient, "neznamy", "cokoli")
    assert odpoved.status_code == 401


def test_role_nahled_na_admin_route_dostane_403(klient):
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved = klient.get("/admin")
    assert odpoved.status_code == 403


def test_role_admin_smi_na_admin_routu(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/admin")
    assert odpoved.status_code == 200


def test_logout_zrusi_session_a_dalsi_pozadavek_presmeruje_na_login(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    klient.post("/logout")

    odpoved = klient.get("/", follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/login"


def test_neplatna_session_cookie_presmeruje_na_login(klient):
    klient.cookies.set("session", "neplatny-podpis")
    odpoved = klient.get("/", follow_redirects=False)
    assert odpoved.status_code == 303
