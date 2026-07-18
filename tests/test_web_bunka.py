"""Testy admin routy pro ruční úpravu buňky + přegenerování zbytku
(úkol 9, viz zadani-faze3-web.md - přepracováno na přání: žádné
zámečky v buňkách, jen "Povolit ruční úpravu" a klik/Enter cyklus
D/N/volno/DOV/OST/NEM, po potvrzení rovnou přegeneruje a uloží zbytek
měsíce od upraveného dne)."""

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
    ids = {"Alena": id_alena}
    for jmeno in VSICH_12[1:]:
        ids[jmeno] = repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    web_auth._NEUSPESNE_POKUSY.clear()
    web_auth._ZABLOKOVANO_DO.clear()

    with TestClient(app, base_url="https://testserver") as klient:
        klient.post("/login", data={"jmeno": "admin", "heslo": "tajneheslo"})
        klient.id_alena = id_alena
        klient.ids = ids
        yield klient


@pytest.fixture
def klient_nahled(klient):
    klient.post("/logout")
    klient.post("/login", data={"jmeno": "nahled", "heslo": "tajneheslo2"})
    return klient


def _conn(klient):
    return repo.pripojit(klient.app.state.cesta_db)


def _upravit(klient, hodnota, datum="2026-08-25", mesic="2026-08", zamestnanec_id=None):
    return klient.post(
        f"/rozpis/bunka/{zamestnanec_id or klient.id_alena}/{datum}",
        data={"mesic": mesic, "hodnota": hodnota},
    )


def test_nahled_dostane_403(klient_nahled):
    odpoved = klient_nahled.post(
        "/rozpis/bunka/1/2026-08-25", data={"mesic": "2026-08", "hodnota": "D"}
    )
    assert odpoved.status_code == 403


def test_upravit_bunku_neexistujiciho_zamestnance_404(klient):
    """Audit: bez kontroly by INSERT do smena spadl na syrový
    sqlite3.IntegrityError (cizí klíč) → 500."""
    odpoved = _upravit(klient, "D", zamestnanec_id=999999)
    assert odpoved.status_code == 404


def test_upravit_bunku_na_denni_ulozi_ale_nezamkne_natrvalo(klient):
    """Na přání: ruční úprava je jednorázová korekce, ne trvalý
    požadavek - i po přegenerování jde bez dalšího zásahu znovu
    přepsat (např. dalším kliknutím nebo hlavním tlačítkem)."""
    odpoved = _upravit(klient, "D")
    assert odpoved.status_code == 200

    smena = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25))
    assert smena.typ == "D"
    assert smena.locked is False


def test_upravit_bunku_na_nocni(klient):
    _upravit(klient, "N")
    smena = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25))
    assert smena.typ == "N"


def test_upravit_bunku_na_volno_smaze_nezamcenou_smenu(klient):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 25): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)  # nezamčená - ulozit_rozpis nezamyká

    odpoved = _upravit(klient, "")
    assert odpoved.status_code == 200
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25)) is None


def test_upravit_bunku_na_dov_vytvori_jednodenni_nedostupnost(klient):
    odpoved = _upravit(klient, "DOV")
    assert odpoved.status_code == 200

    ned = repo.nedostupnost_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25))
    assert ned.typ == "DOV"
    assert ned.od == ned.do == date(2026, 8, 25)
    assert repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25)) is None


def test_zamcenou_bunku_nejde_upravit(klient):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 25): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    smena_id = repo.smena_pro_den(conn, klient.id_alena, date(2026, 8, 25)).id
    repo.zamknout_smeny(conn, [smena_id])

    odpoved = _upravit(klient, "N")
    assert odpoved.status_code == 200

    smena_po = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 25))
    assert smena_po.typ == "D"  # beze změny
    assert smena_po.locked is True


def test_zamcena_bunka_neni_v_mrizce_editovatelna(klient):
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 25): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    smena_id = repo.smena_pro_den(conn, klient.id_alena, date(2026, 8, 25)).id
    repo.zamknout_smeny(conn, [smena_id])

    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert f"/rozpis/bunka/{klient.id_alena}/2026-08-25" not in odpoved.text


def test_upravit_bunku_vicedenni_dov_nezapise_castecnou_smenu(klient):
    """Nález auditu appky: den v rozsahu vícedenní DOV se dřív nejdřív
    zapsal jako směna D (nastavit_smenu, commitne se hned) a AŽ POTOM
    spadl na ValueError kvůli vícedenní nedostupnosti
    (nastavit_nedostupnost_jednoho_dne) - směna D zůstala v DB uložená
    vedle dovolené, aniž by se to projevilo jako chyba. Oprava ověří obě
    podmínky PŘED jakýmkoli zápisem."""
    conn = _conn(klient)
    repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 20), date(2026, 8, 27), "DOV")

    odpoved = _upravit(klient, "D", datum="2026-08-25")
    assert odpoved.status_code == 200

    assert repo.smena_pro_den(conn, klient.id_alena, date(2026, 8, 25)) is None
    ned = repo.nedostupnost_pro_den(conn, klient.id_alena, date(2026, 8, 25))
    assert ned is not None and ned.typ == "DOV" and ned.od == date(2026, 8, 20)


def test_nahled_nevidi_klikaci_formular_v_mrizce(klient_nahled):
    odpoved = klient_nahled.get("/rozpis")
    assert "/rozpis/bunka/" not in odpoved.text


def test_admin_vidi_klikaci_formular_pro_editovatelnou_bunku(klient):
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert f"/rozpis/bunka/{klient.id_alena}/2026-08-25" in odpoved.text


def test_prazdna_volno_bunka_ma_klikaci_tecku(klient):
    """Audit: prázdné tlačítko (bez textu) v prohlížeči vypadalo, že tam
    není co kliknout - přidat službu na volný den tak prakticky nešlo."""
    odpoved = klient.get("/rozpis?mesic=2026-08")
    zacatek = odpoved.text.find(f"/rozpis/bunka/{klient.id_alena}/2026-08-25")
    konec = odpoved.text.find("</form>", zacatek)
    assert "bunka-tlacitko-prazdna" in odpoved.text[zacatek:konec]
    assert "&middot;" in odpoved.text[zacatek:konec]


def test_povolit_rucni_upravu_checkbox_je_na_strance(klient):
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert 'id="chk-rucni-uprava"' in odpoved.text
    assert "Povolit ruční úpravu" in odpoved.text


def test_upravit_bunku_nezamyka_natrvalo_ani_dny_pred_upravou(klient):
    """Na přání: ruční úprava není trvalý požadavek - dny před upraveným
    dnem (pokud nejsou skutečná minulost) zůstávají po přegenerování
    volně přeplánovatelné, ne trvale zamčené."""
    conn = _conn(klient)
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 15): "D", ("Alena", 28): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    _upravit(klient, "N", datum="2026-08-20")

    # jen Alenina směna - s 12 lidmi má po přegenerování skoro každý
    # den víc směn (jiných zaměstnanců), agregace přes celý den by je
    # navzájem přepsala
    smena_15 = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 15))
    assert smena_15.locked is False  # srpen je celý budoucnost, nic se natrvalo nezamklo

    smena_20 = repo.smena_pro_den(_conn(klient), klient.id_alena, date(2026, 8, 20))
    assert smena_20.typ == "N"
    assert smena_20.locked is False  # i upravená buňka jde dál volně přeplánovat


def test_upravit_bunku_prehegeneruje_a_ulozi_zbytek(klient):
    odpoved = _upravit(klient, "D", datum="2026-08-05")
    assert odpoved.status_code == 200
    assert "Rozpis vygenerován" in odpoved.text

    # zbytek měsíce (po 5.8.) je teď reálně vyplněný, ne jen ta jedna buňka
    smeny = repo.smeny_v_mesici(_conn(klient), 2026, 8)
    assert len(smeny) > 1


def test_odebrani_ze_smeny_muze_byt_doplneno_nahradou(klient):
    """Na přání: odebrání zaměstnance ze směny nesmí nechat den
    podstavený, pokud je možné doplnit náhradu - den se třemi lidmi na
    denní (přesně denni_min z config.yaml) po odebrání jednoho spadne
    pod tvrdé minimum, solver musí najít náhradu."""
    conn = _conn(klient)
    trojice = VSICH_12[:3]  # Alena, Bedřich, Cyril
    schedule = Schedule(
        rok=2026, mesic=8, jmena=tuple(trojice),
        smeny={(jmeno, 15): "D" for jmeno in trojice},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    ids_trojice = [
        repo.smena_pro_den(conn, klient.ids[jmeno], date(2026, 8, 15)).id for jmeno in trojice
    ]
    # Bedřich a Cyril zamčení (zůstávají), Alena bude ta odebraná
    repo.zamknout_smeny(conn, ids_trojice[1:])

    odpoved = _upravit(klient, "", datum="2026-08-15", zamestnanec_id=klient.id_alena)
    assert odpoved.status_code == 200
    assert "nelze sestavit" not in odpoved.text

    smeny_15 = [s for s in repo.smeny_v_mesici(_conn(klient), 2026, 8) if s.datum.day == 15]
    pocet_d = sum(1 for s in smeny_15 if s.typ == "D")
    assert pocet_d >= 3  # doplněno zpět na tvrdé minimum (config.yaml denni_min=3)
