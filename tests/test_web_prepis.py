"""Testy admin/nahled rout pro přepis do Cygnusu a PDF (úkol 7)."""

import tempfile
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from solver.schedule import Schedule
from web import app as web_app_modul
from web import auth as web_auth
from web.app import app


@pytest.fixture
def klient(tmp_path):
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
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


def test_bez_loginu_presmeruje_na_login():
    with TestClient(app, base_url="https://testserver") as klient:
        odpoved = klient.get("/rozpis/prepis", follow_redirects=False)
        assert odpoved.status_code == 303
        assert odpoved.headers["location"] == "/login"


def test_prepis_ukazuje_jmeno_a_smenu(klient):
    odpoved = klient.get("/rozpis/prepis?mesic=2026-08")
    assert odpoved.status_code == 200
    assert "Alena" in odpoved.text
    assert "Denní" in odpoved.text


def test_prepis_odkaz_na_pdf_je_na_strance(klient):
    odpoved = klient.get("/rozpis/prepis?mesic=2026-08")
    assert "/rozpis/pdf?mesic=2026-08" in odpoved.text


def test_nahled_smi_listovat_libovolny_mesic(klient_nahled):
    # nahled smí navigovat stejně jako admin (na přání zrušeno omezení
    # "jen aktuální měsíc" - viz STAV-FAZE3.md)
    odpoved = klient_nahled.get("/rozpis/prepis?mesic=1999-01")
    assert odpoved.status_code == 200
    assert "01/1999" in odpoved.text


def test_pdf_stahne_platny_soubor(klient):
    odpoved = klient.get("/rozpis/pdf?mesic=2026-08")
    assert odpoved.status_code == 200
    assert odpoved.headers["content-type"] == "application/pdf"
    assert odpoved.content.startswith(b"%PDF")
    assert "rozpis-2026-08.pdf" in odpoved.headers["content-disposition"]


def test_nahled_smi_stahnout_pdf(klient_nahled):
    odpoved = klient_nahled.get("/rozpis/pdf")
    assert odpoved.status_code == 200
    assert odpoved.content.startswith(b"%PDF")


def test_pdf_uklidi_docasny_soubor_i_pri_chybe(klient, monkeypatch):
    """Audit: chyba uvnitř vygenerovat_pdf nesmí nechat soubor v /tmp -
    BackgroundTask úklid se dřív registroval jen při úspěchu."""
    zaznamenane_cesty = []
    puvodni_mkstemp = tempfile.mkstemp

    def sledovany_mkstemp(*args, **kwargs):
        fd, cesta = puvodni_mkstemp(*args, **kwargs)
        zaznamenane_cesty.append(cesta)
        return fd, cesta

    monkeypatch.setattr(web_app_modul.tempfile, "mkstemp", sledovany_mkstemp)

    def spadni(*args, **kwargs):
        raise RuntimeError("simulovaná chyba v reportlab")

    monkeypatch.setattr(web_app_modul, "vygenerovat_pdf", spadni)

    with pytest.raises(RuntimeError):
        klient.get("/rozpis/pdf?mesic=2026-08")

    assert len(zaznamenane_cesty) == 1
    assert not Path(zaznamenane_cesty[0]).exists()
