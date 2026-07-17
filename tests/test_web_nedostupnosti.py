"""Testy admin rout pro nedostupnosti a nastavení (úkol 5, viz zadani-faze3-web.md)."""

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


# --- oprávnění ---

@pytest.mark.parametrize(
    "metoda,cesta",
    [
        ("get", "/admin/nedostupnosti"),
        ("get", "/admin/nedostupnosti/nova"),
        ("get", "/admin/nastaveni"),
    ],
)
def test_nahled_dostane_403(klient_nahled, metoda, cesta):
    odpoved = getattr(klient_nahled, metoda)(cesta)
    assert odpoved.status_code == 403


# --- nedostupnosti: vytvoření ---

def test_vytvoreni_nedostupnosti(klient):
    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-03",
            "do": "2026-08-09",
            "typ": "DOV",
        },
    )
    assert odpoved.status_code == 200
    assert "Alena" in odpoved.text

    nedostupnosti = repo.vsechny_nedostupnosti(_conn(klient))
    assert len(nedostupnosti) == 1
    assert nedostupnosti[0].typ == "DOV"


def test_vytvoreni_nedostupnosti_typ_svz(klient):
    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-03",
            "do": "2026-08-03",
            "typ": "SVZ",
        },
    )
    assert odpoved.status_code == 200
    assert repo.vsechny_nedostupnosti(_conn(klient))[0].typ == "SVZ"


def test_vytvoreni_s_prekryvem_vraci_varovani_ale_ulozi(klient):
    conn = _conn(klient)
    repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-08",
            "do": "2026-08-12",
            "typ": "OST",
        },
    )
    assert odpoved.status_code == 200
    assert "překrývá" in odpoved.text
    assert len(repo.vsechny_nedostupnosti(_conn(klient))) == 2


def test_vytvoreni_bez_prekryvu_bez_varovani(klient):
    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-03",
            "do": "2026-08-09",
            "typ": "DOV",
        },
    )
    assert "překrývá" not in odpoved.text


def test_vytvoreni_s_obracenym_rozsahem_vraci_chybu_a_neuklada(klient):
    """Audit: od > do by se dřív tiše uložilo jako záznam, který ve
    skutečnosti nic neblokuje."""
    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-09",
            "do": "2026-08-03",
            "typ": "DOV",
        },
    )
    assert odpoved.status_code == 400
    assert repo.vsechny_nedostupnosti(_conn(klient)) == []


def test_varovani_jednotne_cislo_ma_spravny_tvar(klient):
    """Audit: skloňování "1 další nedostupnost" (ne "...nedostupnosti")."""
    conn = _conn(klient)
    repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-08",
            "do": "2026-08-12",
            "typ": "OST",
        },
    )
    assert "1 další nedostupnost se" in odpoved.text
    assert "1 další nedostupnosti" not in odpoved.text


def test_varovani_pro_dve_prekryvajici_ma_spravny_tvar(klient):
    conn = _conn(klient)
    repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")
    repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 4), date(2026, 8, 10), "NEM")

    odpoved = klient.post(
        "/admin/nedostupnosti/nova",
        data={
            "zamestnanec_id": klient.id_alena,
            "od": "2026-08-05",
            "do": "2026-08-11",
            "typ": "OST",
        },
    )
    assert "2 další nedostupnosti se" in odpoved.text


# --- nedostupnosti: úprava ---

def test_uprava_nedostupnosti(klient):
    conn = _conn(klient)
    ned_id = repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    odpoved = klient.post(
        f"/admin/nedostupnosti/{ned_id}/upravit",
        data={"od": "2026-08-05", "do": "2026-08-06", "typ": "OST", "poznamka": "změna"},
    )
    assert odpoved.status_code == 200

    ned = repo.nedostupnost_podle_id(_conn(klient), ned_id)
    assert ned.od == date(2026, 8, 5)
    assert ned.typ == "OST"
    assert ned.poznamka == "změna"


def test_uprava_nedostupnosti_ktera_neexistuje_404(klient):
    odpoved = klient.post(
        "/admin/nedostupnosti/9999/upravit",
        data={"od": "2026-08-05", "do": "2026-08-06", "typ": "OST"},
    )
    assert odpoved.status_code == 404


def test_uprava_s_obracenym_rozsahem_vraci_chybu_a_nezmeni_zaznam(klient):
    conn = _conn(klient)
    ned_id = repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    odpoved = klient.post(
        f"/admin/nedostupnosti/{ned_id}/upravit",
        data={"od": "2026-08-09", "do": "2026-08-03", "typ": "DOV"},
    )
    assert odpoved.status_code == 400

    puvodni = repo.nedostupnost_podle_id(_conn(klient), ned_id)
    assert puvodni.od == date(2026, 8, 3)
    assert puvodni.do == date(2026, 8, 9)


# --- nedostupnosti: smazání ---

def test_smazani_nedostupnosti(klient):
    conn = _conn(klient)
    ned_id = repo.pridat_nedostupnost(conn, klient.id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    odpoved = klient.post(f"/admin/nedostupnosti/{ned_id}/smazat")
    assert odpoved.status_code == 200
    assert repo.nedostupnost_podle_id(_conn(klient), ned_id) is None


# --- nastavení ---

def test_nastaveni_formular_bez_ulozeni_ukazuje_prazdny_stav(klient):
    odpoved = klient.get("/admin/nastaveni")
    assert odpoved.status_code == 200
    assert "config.yaml" in odpoved.text


def test_ulozeni_nastaveni(klient):
    odpoved = klient.post(
        "/admin/nastaveni/normalni",
        data={
            "denni_min": "3", "denni_max": "4", "nocni_min": "2", "nocni_max": "2",
            "max_v_rade": "3", "max_smen_mesic": "15",
        },
    )
    assert odpoved.status_code == 200

    nastaveni = repo.nastaveni_pro_profil(_conn(klient), "normalni")
    assert nastaveni.denni_min == 3
    assert nastaveni.max_smen_mesic == 15
    assert nastaveni.plne_obsazeni == 10  # výchozí váha, nezadaná ve formuláři


def test_ulozeni_nastaveni_krizoveho_profilu_neovlivni_normalni(klient):
    klient.post(
        "/admin/nastaveni/krizovy",
        data={
            "denni_min": "3", "denni_max": "4", "nocni_min": "1", "nocni_max": "2",
            "max_v_rade": "3", "max_smen_mesic": "18",
        },
    )
    assert repo.nastaveni_pro_profil(_conn(klient), "krizovy").nocni_min == 1
    assert repo.nastaveni_pro_profil(_conn(klient), "normalni") is None


def test_ulozeni_neplatneho_nastaveni_vraci_chybu(klient):
    odpoved = klient.post(
        "/admin/nastaveni/normalni",
        data={
            "denni_min": "5", "denni_max": "2", "nocni_min": "2", "nocni_max": "2",
            "max_v_rade": "3", "max_smen_mesic": "15",
        },
    )
    assert odpoved.status_code == 400
    assert repo.nastaveni_pro_profil(_conn(klient), "normalni") is None


def test_ulozeni_nastaveni_pod_domenovym_minimem_vraci_chybu(klient):
    """Audit: validace dřív hlídala jen min<=max>=0, ne CLAUDE.md pravidla
    (denní 3-4, noční tvrdě 1-2) - denni_min=0 dřív prošlo bez varování."""
    odpoved = klient.post(
        "/admin/nastaveni/normalni",
        data={
            "denni_min": "0", "denni_max": "4", "nocni_min": "2", "nocni_max": "2",
            "max_v_rade": "3", "max_smen_mesic": "15",
        },
    )
    assert odpoved.status_code == 400
    assert repo.nastaveni_pro_profil(_conn(klient), "normalni") is None


def test_ulozeni_nastaveni_nad_domenovym_maximem_vraci_chybu(klient):
    odpoved = klient.post(
        "/admin/nastaveni/normalni",
        data={
            "denni_min": "3", "denni_max": "4", "nocni_min": "1", "nocni_max": "3",
            "max_v_rade": "3", "max_smen_mesic": "15",
        },
    )
    assert odpoved.status_code == 400
    assert repo.nastaveni_pro_profil(_conn(klient), "normalni") is None


def test_ulozeni_nastaveni_krizovy_profil_nocni_min_1_projde(klient):
    """Krizový profil smí sáhnout na spodní hranici tvrdého rozsahu 1-2."""
    odpoved = klient.post(
        "/admin/nastaveni/krizovy",
        data={
            "denni_min": "3", "denni_max": "4", "nocni_min": "1", "nocni_max": "2",
            "max_v_rade": "3", "max_smen_mesic": "18",
        },
    )
    assert odpoved.status_code == 200
    assert repo.nastaveni_pro_profil(_conn(klient), "krizovy").nocni_min == 1


def test_neznamy_profil_404(klient):
    odpoved = klient.post(
        "/admin/nastaveni/exoticky",
        data={
            "denni_min": "3", "denni_max": "4", "nocni_min": "2", "nocni_max": "2",
            "max_v_rade": "3", "max_smen_mesic": "15",
        },
    )
    assert odpoved.status_code == 404
