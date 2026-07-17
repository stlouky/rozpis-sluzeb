"""Testy webové kostry a přihlášení (úkol 1, viz zadani-faze3-web.md)."""

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
    conn.close()

    # base_url na https, ať se v testu reálně uplatní Secure cookie flag
    # (viz CLAUDE.md, bezpečnostní invarianty).
    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"

    # _NEUSPESNE_POKUSY/_ZABLOKOVANO_DO jsou module-global (stejně jako
    # _SESSIONS) - bez resetu by neúspěšné pokusy z jednoho testu (stejná
    # jména "admin"/"nahled" napříč testy) mohly ovlivnit test spuštěný
    # po něm.
    web_auth._NEUSPESNE_POKUSY.clear()
    web_auth._ZABLOKOVANO_DO.clear()

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


def test_opakovane_spatne_heslo_zablokuje_i_spravne_heslo(klient):
    for _ in range(web_auth.MAX_NEUSPESNYCH_POKUSU):
        _prihlasit(klient, "admin", "spatne-heslo")

    # I správné heslo je teď odmítnuté - blokace platí pro jméno, ne pro
    # konkrétní (špatné) heslo.
    odpoved = _prihlasit(klient, "admin", "tajneheslo")
    assert odpoved.status_code == 401
    assert "Příliš mnoho" in odpoved.text
    assert "session" not in klient.cookies


def test_zablokovani_se_tyka_i_neexistujiciho_jmena(klient):
    """Blokace se počítá podle zadaného jména bez ohledu na existenci účtu -
    jinak by časování/hláška prozradily, které jméno je platné."""
    for _ in range(web_auth.MAX_NEUSPESNYCH_POKUSU):
        _prihlasit(klient, "neexistuje", "cokoli")

    assert web_auth.prihlaseni_zablokovano("neexistuje") is True


def test_par_spatnych_pokusu_pod_limitem_neblokuje(klient):
    for _ in range(web_auth.MAX_NEUSPESNYCH_POKUSU - 1):
        _prihlasit(klient, "admin", "spatne-heslo")

    odpoved = _prihlasit(klient, "admin", "tajneheslo")
    assert odpoved.status_code == 200
    assert "session" in klient.cookies


def test_uspesne_prihlaseni_resetuje_pocet_pokusu(klient):
    _prihlasit(klient, "admin", "spatne-heslo")
    _prihlasit(klient, "admin", "tajneheslo")  # úspěch, resetuje počítadlo

    for _ in range(web_auth.MAX_NEUSPESNYCH_POKUSU - 1):
        _prihlasit(klient, "admin", "spatne-heslo")

    # Kdyby se počítadlo neresetovalo, tenhle pokus by už byl za limitem.
    odpoved = _prihlasit(klient, "admin", "tajneheslo")
    assert odpoved.status_code == 200


def test_zablokovani_vyprsi_po_case(klient, monkeypatch):
    cas = [1000.0]
    monkeypatch.setattr(web_auth.time, "monotonic", lambda: cas[0])

    for _ in range(web_auth.MAX_NEUSPESNYCH_POKUSU):
        _prihlasit(klient, "admin", "spatne-heslo")
    assert web_auth.prihlaseni_zablokovano("admin") is True

    cas[0] += web_auth.DOBA_ZABLOKOVANI_S + 1
    assert web_auth.prihlaseni_zablokovano("admin") is False

    odpoved = _prihlasit(klient, "admin", "tajneheslo")
    assert odpoved.status_code == 200


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
