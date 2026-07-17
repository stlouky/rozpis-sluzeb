"""Testy sjednocené cesty k DB a startovní kontroly webu.

Incident: web a CLI měly každý svou nezávislou definici výchozí cesty k
SQLite souboru a rozjely se na dva různé soubory - web se tiše připojil
na starou/prázdnou DB bez tabulky uzivatel, zatímco CLI mezitím
zapisovalo přes --db do jiného souboru. Viz db/cesta.py a web/db.py.
"""

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from db.cli import main as cli_main
from web.app import app
from web.db import OCEKAVANE_TABULKY, overit_databazi


def test_cli_a_web_pouzivaji_stejnou_funkci_pro_vychozi_cestu():
    import db.cesta
    import web.app as web_app_modul

    # Reference na STEJNOU funkci, ne porovnání app.state.cesta_db - tu
    # v běžící sadě přepisují fixture jiných testů (test_web.py,
    # test_mrizka.py), takže srovnání hodnoty je pořadím-závislé. Kontrola
    # identity funkce je přesně to, co má regresi hlídat (viz incident
    # výš): obě vstupní místa musí sahat na STEJNOU definici, ne dvě
    # nezávislé, byť momentálně stejně vyhlížející.
    assert web_app_modul.vychozi_cesta_db is db.cesta.vychozi_cesta_db


def test_web_pripojeny_na_db_vytvorenou_pres_cli_vidi_uzivatele(tmp_path):
    cesta_db = tmp_path / "rozpis.db"
    # Záměrně přes CLI main(), ne přímým voláním repo funkcí - přesně tahle
    # cesta (CLI založí DB, web se na ni později připojí) je to, co se
    # dřív rozjelo na dva různé soubory.
    cli_main(["--db", str(cesta_db), "vytvorit-uzivatele", "admin", "admin", "--heslo", "tajneheslo"])

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    with TestClient(app, base_url="https://testserver") as klient:
        odpoved = klient.post("/login", data={"jmeno": "admin", "heslo": "tajneheslo"})
        assert odpoved.status_code == 200
        assert "admin" in odpoved.text


def test_web_odmitne_start_kdyz_db_neexistuje(tmp_path):
    app.state.cesta_db = tmp_path / "neexistuje.db"
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    with pytest.raises(RuntimeError, match="neexistuje"):
        with TestClient(app, base_url="https://testserver"):
            pass


def test_web_odmitne_start_kdyz_db_chybi_tabulka(tmp_path):
    # simuluje přesně reálný incident: existující DB soubor bez novější
    # tabulky (tady uzivatel, protože vznikla později než zamestnanec)
    cesta_db = tmp_path / "stara.db"
    conn = repo.pripojit(cesta_db)
    conn.execute("CREATE TABLE zamestnanec (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    with pytest.raises(RuntimeError, match="uzivatel"):
        with TestClient(app, base_url="https://testserver"):
            pass


def test_overit_databazi_projde_na_plnem_schematu(tmp_path):
    cesta_db = tmp_path / "test.db"
    repo.pripojit_a_inicializovat(cesta_db).close()
    overit_databazi(cesta_db)  # nesmí vyhodit


def test_ocekavane_tabulky_odpovidaji_schematu(tmp_path):
    # kdyby v budoucnu přibyla další tabulka do schema.sql a
    # OCEKAVANE_TABULKY se zapomnělo doplnit, tahle kontrola to odhalí
    # (na rozdíl od porovnání s natvrdo vypsaným seznamem v testu)
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    skutecne_tabulky = {
        radek[0]
        for radek in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        ).fetchall()
    }
    conn.close()
    assert OCEKAVANE_TABULKY == skutecne_tabulky
