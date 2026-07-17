"""Testy admin routy pro klikací úpravu buňky (úkol 8, viz zadani-faze3-web.md)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from solver.schedule import Schedule
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


def _klik(klient, datum="2026-08-05", mesic="2026-08"):
    return klient.post(
        f"/rozpis/bunka/{klient.id_alena}/{datum}", data={"mesic": mesic}
    )


def test_nahled_dostane_403(klient_nahled):
    odpoved = klient_nahled.post(
        "/rozpis/bunka/1/2026-08-05", data={"mesic": "2026-08"}
    )
    assert odpoved.status_code == 403


def test_klik_na_volnou_bunku_nastavi_denni(klient):
    odpoved = _klik(klient)
    assert odpoved.status_code == 200  # TestClient následuje redirect zpět na mřížku

    smena = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 5))
    assert smena.typ == "D"


def test_cyklus_d_n_volno_d(klient):
    _klik(klient)
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 5)).typ == "D"

    _klik(klient)
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 5)).typ == "N"

    _klik(klient)
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 5)) is None

    _klik(klient)
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 5)).typ == "D"


def test_zamcenou_smenu_klik_nezmeni(klient):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 5): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    smena_id = repo.smena_pro_den(conn, klient.id_alena, date(2026, 8, 5)).id
    repo.zamknout_smeny(conn, [smena_id])

    odpoved = _klik(klient)
    assert odpoved.status_code == 200

    smena_po = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 5))
    assert smena_po.typ == "D"
    assert smena_po.locked is True


def test_zamcena_bunka_neni_v_mrizce_klikatelna(klient):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 5): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    smena_id = repo.smena_pro_den(conn, klient.id_alena, date(2026, 8, 5)).id
    repo.zamknout_smeny(conn, [smena_id])

    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert f"/rozpis/bunka/{klient.id_alena}/2026-08-05" not in odpoved.text


def test_nahled_nevidi_klikaci_formular_v_mrizce(klient_nahled):
    odpoved = klient_nahled.get("/rozpis")
    assert "/rozpis/bunka/" not in odpoved.text


def test_admin_vidi_klikaci_formular_pro_nezamcenou_bunku(klient):
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert f"/rozpis/bunka/{klient.id_alena}/2026-08-05" in odpoved.text


def test_mrizka_oznaci_porusene_pravidlo_po_editaci(klient):
    # N 5.8. -> D 6.8. je zakázaný přechod (viz solver/validace.py)
    _klik(klient, datum="2026-08-05")  # D
    _klik(klient, datum="2026-08-05")  # N
    _klik(klient, datum="2026-08-06")  # D

    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert "porusena" in odpoved.text
    assert "po noční" in odpoved.text
