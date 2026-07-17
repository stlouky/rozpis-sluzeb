"""Testy admin routy pro generování rozpisu (úkol 6+9, viz zadani-faze3-web.md)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from web import app as web_app_modul
from web import auth as web_auth
from web.app import app

VSICH_12 = [
    "Alena", "Bedřich", "Cyril", "Dana", "Emil", "Frantiska",
    "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]


def _klient(tmp_path, jmena_zamestnancu):
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    for jmeno in jmena_zamestnancu:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    web_auth._NEUSPESNE_POKUSY.clear()
    web_auth._ZABLOKOVANO_DO.clear()
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def klient(tmp_path, monkeypatch):
    # Kratší time_limit_s než produkční GENEROVANI_TIME_LIMIT_S (30 s) -
    # test nepotřebuje důkaz optimality, jen nějaké platné řešení
    # (a determinismus je dán seedem, ne délkou běhu).
    monkeypatch.setattr(web_app_modul, "GENEROVANI_TIME_LIMIT_S", 5.0)
    # 12 zaměstnanců - splnitelné zadání (stejná sestava jako config.yaml).
    with _klient(tmp_path, VSICH_12) as klient:
        klient.post("/login", data={"jmeno": "admin", "heslo": "tajneheslo"})
        yield klient


@pytest.fixture
def klient_nesplnitelne(tmp_path):
    # Jen 2 zaměstnanci - min. obsazení (3 denní + 2 noční) je nesplnitelné,
    # stejný vzor jako test_cli.py:test_cli_generuj_nesplnitelne_zadani...
    # (rychlé - CP-SAT nesplnitelnost tady dokáže lokálně, bez čekání na
    # celý time_limit_s).
    with _klient(tmp_path, ["Alena", "Bedřich"]) as klient:
        klient.post("/login", data={"jmeno": "admin", "heslo": "tajneheslo"})
        yield klient


@pytest.fixture
def klient_nahled(klient):
    klient.post("/logout")
    klient.post("/login", data={"jmeno": "nahled", "heslo": "tajneheslo2"})
    return klient


def _conn(klient):
    return repo.pripojit(klient.app.state.cesta_db)


def _generovat(klient, mesic="2026-08", profil="normalni"):
    return klient.post("/rozpis/generovat", data={"mesic": mesic, "profil": profil})


def _potvrdit(klient, mesic="2026-08", profil="normalni"):
    return klient.post(
        "/rozpis/generovat/potvrdit", data={"mesic": mesic, "profil": profil}
    )


def test_optimalizovany_profil_zapne_prioritizaci_obsazeni(klient, monkeypatch):
    """Úkol 9c (na přání, upřesněno): "optimalizovany" musí solveru
    předat prioritizovat_obsazeni=True (dvoufázové řešení, viz
    solver/core.py) - jen vyšší váha plne_obsazeni na tohle nestačila
    (viz komentář u web/app.py:_vyresit)."""
    zachycene_kwargs = {}
    puvodni = web_app_modul.generate_schedule

    def zaznamenej(config, **kwargs):
        zachycene_kwargs.update(kwargs)
        return puvodni(config, **kwargs)

    monkeypatch.setattr(web_app_modul, "generate_schedule", zaznamenej)

    _generovat(klient, profil="optimalizovany")
    assert zachycene_kwargs.get("prioritizovat_obsazeni") is True

    zachycene_kwargs.clear()
    _generovat(klient, profil="normalni")
    assert zachycene_kwargs.get("prioritizovat_obsazeni") is False


def test_nahled_dostane_403(klient_nahled):
    odpoved = _generovat(klient_nahled)
    assert odpoved.status_code == 403


def test_generovani_poprve_ukaze_diff_a_neuklada(klient):
    """Úkol 9: diff před uložením - první generování pro prázdný měsíc
    má "bylo: volno" pro každou změnu a NIC se rovnou neuloží."""
    odpoved = _generovat(klient)
    assert odpoved.status_code == 200
    assert "Náhled nového rozpisu" in odpoved.text
    assert "Potvrdit a uložit" in odpoved.text

    assert repo.smeny_v_mesici(_conn(klient), 2026, 8) == []


def test_generovani_potvrzeni_ulozi_rozpis(klient):
    _generovat(klient)
    odpoved = _potvrdit(klient)
    assert odpoved.status_code == 200  # TestClient defaultně následuje redirect
    assert "Rozpis vygenerován" in odpoved.text

    smeny = repo.smeny_v_mesici(_conn(klient), 2026, 8)
    assert len(smeny) > 0


def test_generovani_je_deterministicke(klient):
    """Pevný seed (viz web/app.py:GENEROVANI_SEED) vynucuje
    num_search_workers=1 a zároveň dělá výsledek reprodukovatelný -
    dva nezávislé běhy nad stejnými daty musí dát stejný rozpis."""
    _generovat(klient)
    _potvrdit(klient)
    prvni = {
        (s.zamestnanec_id, s.datum, s.typ) for s in repo.smeny_v_mesici(_conn(klient), 2026, 8)
    }

    # druhé kolo nad stejnými (teď uloženými) daty - beze změny, diff
    # prázdný, rovnou se "uloží" (no-op) a přesměruje
    odpoved = _generovat(klient)
    assert odpoved.status_code == 200
    assert "beze změny" in odpoved.text

    druhy = {
        (s.zamestnanec_id, s.datum, s.typ) for s in repo.smeny_v_mesici(_conn(klient), 2026, 8)
    }
    assert prvni == druhy


def test_zamcena_smena_se_nezmeni_pri_pregenerovani(klient):
    """Úkol 9 zadaný test: "locked se nezmění". Od úkolu 9 dál solver
    zamčené směny zná (Config.pevne_smeny, viz db/bridge.py) a je nutí
    vygenerovat přesně stejnou hodnotu - konflikt (PreskocenaSmena z
    úkolu 2/6) se tak přes tenhle tok už nemůže stát, ale samotná
    neměnnost zamčené hodnoty musí platit dál."""
    conn = _conn(klient)
    _generovat(klient)
    _potvrdit(klient)

    smena = repo.smeny_v_mesici(conn, 2026, 8)[0]
    puvodni_typ = smena.typ
    repo.zamknout_smeny(conn, [smena.id])

    _generovat(klient)
    odpoved = _potvrdit(klient)
    assert odpoved.status_code == 200

    zamcena_po = next(
        s for s in repo.smeny_v_mesici(_conn(klient), 2026, 8) if s.id == smena.id
    )
    assert zamcena_po.typ == puvodni_typ
    assert zamcena_po.locked is True


def test_generovani_nesplnitelne_zobrazi_diagnostiku_ne_500(klient_nesplnitelne):
    odpoved = _generovat(klient_nesplnitelne)
    assert odpoved.status_code == 200
    assert "nelze sestavit" in odpoved.text
    assert "Zkusit krizový profil" in odpoved.text
    assert repo.smeny_v_mesici(_conn(klient_nesplnitelne), 2026, 8) == []


def test_generovani_krizovy_profil_nenabizi_dalsi_zkuseni(klient_nesplnitelne):
    odpoved = _generovat(klient_nesplnitelne, profil="krizovy")
    assert odpoved.status_code == 200
    assert "nelze sestavit" in odpoved.text
    assert "Zkusit krizový profil" not in odpoved.text


def test_generovani_nesplnitelne_bez_zamcenych_nenabizi_odemknuti(klient_nesplnitelne):
    odpoved = _generovat(klient_nesplnitelne)
    assert "Odemknout budoucí zamčené směny" not in odpoved.text


def test_rozpis_zobrazi_potvrzeni_z_query_parametru(klient):
    """GET /rozpis?vygenerovano=1&... (kam POST /rozpis/generovat/potvrdit
    přesměruje po úspěchu) musí banner ukázat i samostatně."""
    odpoved = klient.get(
        "/rozpis",
        params={
            "mesic": "2026-08",
            "vygenerovano": "1",
            "generovani_status": "OPTIMAL",
            "generovani_cas": "0.5",
            "preskoceno": "0",
        },
    )
    assert odpoved.status_code == 200
    assert "Rozpis vygenerován" in odpoved.text
    assert "OPTIMAL" in odpoved.text
