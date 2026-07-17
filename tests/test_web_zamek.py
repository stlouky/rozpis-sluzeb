"""Testy automatického zamykání (úkol 9, viz zadani-faze3-web.md).

Ruční zamykání klikem/rozsahem bylo na přání nahrazeno jednodušším
tokem (viz test_web_bunka.py: ruční úprava buňky rovnou přegeneruje a
uloží zbytek měsíce) - tenhle soubor pokrývá jen to, co zůstalo:
automatické zamčení minulosti a "nesplnitelno po zamčení vrátí
použitelnou radu" (zadaný test úkolu 9).
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from solver.schedule import Schedule
from web import app as web_app_modul
from web import auth as web_auth
from web.app import app

VSICH_12 = [
    "Alena", "Bedřich", "Cyril", "Dana", "Emil", "Frantiska",
    "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]


@pytest.fixture
def klient(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app_modul, "GENEROVANI_TIME_LIMIT_S", 5.0)
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    for jmeno in VSICH_12[1:]:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    web_auth._NEUSPESNE_POKUSY.clear()
    web_auth._ZABLOKOVANO_DO.clear()

    with TestClient(app, base_url="https://testserver") as klient:
        klient.post("/login", data={"jmeno": "admin", "heslo": "tajneheslo"})
        klient.id_alena = id_alena
        yield klient


def _conn(klient):
    return repo.pripojit(klient.app.state.cesta_db)


def _ulozit_smenu(klient, den=25, typ="D"):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", den): typ}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    return repo.smena_pro_den(conn, klient.id_alena, date(2026, 8, den))


# --- nesplnitelnost po zamčení (úkol 9 zadaný test: "vrací použitelnou radu") ---

def test_nesplnitelno_po_zamceni_nabidne_odemknuti_a_pomuze(klient):
    conn = _conn(klient)
    # Zamkne Alenu na noční 25.8., pak jí přidá DOV přesně na 25.8. -
    # přímý rozpor (pevná směna vs. nedostupnost stejný den), deterministicky
    # nesplnitelné bez ohledu na zbytek týmu.
    smena = _ulozit_smenu(klient, den=25, typ="N")
    repo.zamknout_smeny(conn, [smena.id])
    repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 25), date(2026, 8, 25), "DOV")

    odpoved = klient.post(
        "/rozpis/generovat", data={"mesic": "2026-08", "profil": "normalni"}
    )
    assert odpoved.status_code == 200
    assert "nelze sestavit" in odpoved.text
    assert "Odemknout budoucí zamčené směny" in odpoved.text

    # klik na nabízenou radu musí problém reálně vyřešit
    odpoved = klient.post(
        "/rozpis/generovat/odemknout-a-zkusit",
        data={"mesic": "2026-08", "profil": "normalni"},
    )
    assert odpoved.status_code == 200
    assert "nelze sestavit" not in odpoved.text
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25)).locked is False


# --- zamknout_minulost integrace (úkol 9) ---

def test_generovani_zamkne_minulost_pred_prepoctem(klient):
    # dnešek je v testech 2026-07-17 - 10.7. je minulost
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=7, jmena=("Alena",), smeny={("Alena", 10): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    assert repo.smena_pro_den(conn, klient.id_alena, date(2026, 7, 10)).locked is False

    klient.post("/rozpis/generovat", data={"mesic": "2026-07", "profil": "normalni"})

    assert repo.smena_pro_den(
        _conn(klient), klient.id_alena, date(2026, 7, 10)
    ).locked is True
