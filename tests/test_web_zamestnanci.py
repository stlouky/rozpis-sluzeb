"""Testy admin routy pro správu zaměstnanců (úkol 4, viz zadani-faze3-web.md)."""

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


# --- oprávnění: nahled nesmí na žádnou z těch rout (invariant #4) ---

def test_nahled_dostane_403_na_seznam(klient_nahled):
    assert klient_nahled.get("/admin/zamestnanci").status_code == 403


def test_nahled_dostane_403_na_novy_formular(klient_nahled):
    assert klient_nahled.get("/admin/zamestnanci/novy").status_code == 403


def test_nahled_dostane_403_na_vytvoreni(klient_nahled):
    odpoved = klient_nahled.post(
        "/admin/zamestnanci/novy",
        data={"jmeno": "Xaver", "aktivni_od": "2026-01-01"},
    )
    assert odpoved.status_code == 403


# --- seznam ---

def test_seznam_defaultne_jen_aktivni(klient):
    id_bedrich = repo.pridat_zamestnance(
        _conn(klient), "Bedřich", date(2020, 1, 1)
    )
    repo.deaktivovat_zamestnance(_conn(klient), id_bedrich, date(2025, 1, 1))

    odpoved = klient.get("/admin/zamestnanci")
    assert "Alena" in odpoved.text
    assert "Bedřich" not in odpoved.text


def test_seznam_s_vsichni_ukaze_i_byvale(klient):
    id_bedrich = repo.pridat_zamestnance(
        _conn(klient), "Bedřich", date(2020, 1, 1)
    )
    repo.deaktivovat_zamestnance(_conn(klient), id_bedrich, date(2025, 1, 1))

    odpoved = klient.get("/admin/zamestnanci?vsichni=1")
    assert "Alena" in odpoved.text
    assert "Bedřich" in odpoved.text


# --- vytvoření ---

def test_vytvoreni_zamestnance(klient):
    odpoved = klient.post(
        "/admin/zamestnanci/novy",
        data={"jmeno": "Cyril", "aktivni_od": "2026-03-01"},
    )
    assert odpoved.status_code == 200  # TestClient následuje redirect na seznam
    assert "Cyril" in odpoved.text

    cyril = repo.zamestnanec_podle_jmena(_conn(klient), "Cyril")
    assert cyril.aktivni_od == date(2026, 3, 1)


def test_vytvoreni_se_stitkem_fyzicka_vypomoc(klient):
    klient.post(
        "/admin/zamestnanci/novy",
        data={"jmeno": "Dana", "aktivni_od": "2026-03-01", "fyzicka_vypomoc": "on"},
    )
    dana = repo.zamestnanec_podle_jmena(_conn(klient), "Dana")
    assert dana.seznam_stitku == ["fyzicka_vypomoc"]


def test_vytvoreni_bez_stitku_kdyz_checkbox_neni_zaskrtnuty(klient):
    klient.post(
        "/admin/zamestnanci/novy",
        data={"jmeno": "Emil", "aktivni_od": "2026-03-01"},
    )
    emil = repo.zamestnanec_podle_jmena(_conn(klient), "Emil")
    assert emil.seznam_stitku == []


def test_vytvoreni_s_neslucitelnou_dvojici(klient):
    """Ve formuláři zaměstnance rovnou dvojice - viz úkol 4 zadání
    ("při nástupu nového člověka se vše nastaví na jednom místě")."""
    klient.post(
        "/admin/zamestnanci/novy",
        data={
            "jmeno": "Frantisek",
            "aktivni_od": "2026-03-01",
            "dvojice_s": [str(klient.id_alena)],
        },
    )
    dvojice = repo.dvojice_vsechny(_conn(klient))
    frantisek = repo.zamestnanec_podle_jmena(_conn(klient), "Frantisek")
    assert any(
        {d.zamestnanec_a_id, d.zamestnanec_b_id} == {frantisek.id, klient.id_alena}
        and d.typ == "rozprostrit"
        for d in dvojice
    )


def test_vytvoreni_s_max_smen_mesic(klient):
    klient.post(
        "/admin/zamestnanci/novy",
        data={"jmeno": "Gustav", "aktivni_od": "2026-03-01", "max_smen_mesic": "5"},
    )
    gustav = repo.zamestnanec_podle_jmena(_conn(klient), "Gustav")
    assert gustav.max_smen_mesic == 5


def test_vytvoreni_bez_jmena_vrati_chybu(klient):
    odpoved = klient.post(
        "/admin/zamestnanci/novy", data={"jmeno": "  ", "aktivni_od": "2026-03-01"}
    )
    assert odpoved.status_code == 400
    assert "Jméno je povinné" in odpoved.text


# --- oprava jména ---

def test_oprava_jmena(klient):
    odpoved = klient.post(
        f"/admin/zamestnanci/{klient.id_alena}/upravit-jmeno", data={"jmeno": "Alena Nová"}
    )
    assert odpoved.status_code == 200
    alena = repo.zamestnanec_podle_id(_conn(klient), klient.id_alena)
    assert alena.jmeno == "Alena Nová"


# --- deaktivace ---

def test_deaktivace_zmizi_ze_seznamu_ale_zustane_s_vsichni(klient):
    odpoved = klient.post(
        f"/admin/zamestnanci/{klient.id_alena}/deaktivovat", data={"aktivni_do": "2020-06-30"}
    )
    assert odpoved.status_code == 200

    assert "Alena" not in klient.get("/admin/zamestnanci").text
    assert "Alena" in klient.get("/admin/zamestnanci?vsichni=1").text


def test_deaktivace_pred_nastupem_vraci_chybu_a_zamestnanec_zustane_aktivni(klient):
    """Audit: aktivni_do před aktivni_od (Alena nastoupila 2020-01-01) by
    ji potichu vyřadilo ze VŠECH "aktivní" dotazů, i zpětně."""
    odpoved = klient.post(
        f"/admin/zamestnanci/{klient.id_alena}/deaktivovat", data={"aktivni_do": "2019-01-01"}
    )
    assert odpoved.status_code == 400
    assert "Alena" in klient.get("/admin/zamestnanci").text


# --- smazání ---

def test_smazani_bez_smeny(klient):
    odpoved = klient.post(f"/admin/zamestnanci/{klient.id_alena}/smazat")
    assert odpoved.status_code == 200
    assert repo.zamestnanec_podle_id(_conn(klient), klient.id_alena) is None


def test_smazani_se_smenou_selze_a_zamestnanec_zustane(klient):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    odpoved = klient.post(f"/admin/zamestnanci/{klient.id_alena}/smazat")
    assert odpoved.status_code == 400
    assert repo.zamestnanec_podle_id(_conn(klient), klient.id_alena) is not None


def test_neexistujici_zamestnanec_404(klient):
    assert klient.get("/admin/zamestnanci/9999/upravit").status_code == 404


def _conn(klient):
    return repo.pripojit(klient.app.state.cesta_db)
