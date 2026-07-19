"""Testy mřížky měsíce (úkol 3, viz zadani-faze3-web.md)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from db import repository as repo
from db.auth import hashovat_heslo
from db.models import NastaveniProfilu
from solver.schedule import Schedule
from web.app import app
from web.mrizka import sestavit_mrizku, sestavit_pozadavky_widget


@pytest.fixture
def conn():
    connection = repo.pripojit(":memory:")
    repo.inicializovat_schema(connection)
    yield connection
    connection.close()


def _ulozit_zakladni_rozpis(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    id_bedrich = repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
        smeny={("Alena", 1): "D", ("Bedřich", 1): "N", ("Bedřich", 2): "N"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    return id_alena, id_bedrich


# --- web/mrizka.py: sestavit_mrizku přímo, bez HTTP ---

def test_sestavit_mrizku_radky_jsou_abecedne_a_obsahuji_smeny(conn):
    _ulozit_zakladni_rozpis(conn)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)

    assert [r.jmeno for r in mrizka.radky] == ["Alena", "Bedřich"]
    alena = mrizka.radky[0]
    assert alena.bunky[0].smena == "D"  # 1.8.
    assert alena.bunky[1].smena is None  # 2.8. - volno
    bedrich = mrizka.radky[1]
    assert bedrich.bunky[0].smena == "N"
    assert bedrich.pocet_n == 2
    assert bedrich.pocet_d == 0


def test_sestavit_mrizku_obsazeni_je_pocet_d_n_za_den(conn):
    _ulozit_zakladni_rozpis(conn)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)

    # 1.8.: Alena D, Bedřich N -> (1, 1); 2.8.: jen Bedřich N -> (0, 1);
    # 3.8.: nikdo -> (0, 0)
    assert mrizka.obsazeni[0] == (1, 1)
    assert mrizka.obsazeni[1] == (0, 1)
    assert mrizka.obsazeni[2] == (0, 0)
    assert len(mrizka.obsazeni) == mrizka.dny[-1]  # jeden záznam na každý den měsíce


def test_sestavit_mrizku_krizove_dny_pod_mesicnim_maximem(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    # 1.8.: oba D (obsazení 2) - měsíční maximum; 2.8.: jen Alena D (1) -
    # pod maximem, tedy "krizový"; 3.8.: nikdo (0) - taky krizový
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
        smeny={("Alena", 1): "D", ("Bedřich", 1): "D", ("Alena", 2): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.krizove_dny[0] is False  # 1.8. - na maximu
    assert mrizka.krizove_dny[1] is True  # 2.8. - pod maximem
    assert mrizka.krizove_dny[2] is True  # 3.8. - pod maximem


def test_sestavit_mrizku_krizove_dny_i_kdyz_je_denni_plne(conn):
    """Noční podstav musí být krizový samostatně, i když má ten den denní
    obsazení na měsíčním maximu - dřív ho plný denní stav "schoval" (viz
    audit)."""
    for jmeno in ("Alena", "Bedřich", "Cyril", "Dana"):
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    # 1.8.: denní i noční na maximu (2, 2); 2.8.: denní pořád plné (2), ale
    # noční jen 1 - podstav, přesto by ho stará logika (jen podle denní)
    # neoznačila jako krizový.
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich", "Cyril", "Dana"),
        smeny={
            ("Alena", 1): "D", ("Bedřich", 1): "D",
            ("Cyril", 1): "N", ("Dana", 1): "N",
            ("Alena", 2): "D", ("Bedřich", 2): "D",
            ("Cyril", 2): "N",
        },
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.obsazeni[0] == (2, 2)
    assert mrizka.obsazeni[1] == (2, 1)
    assert mrizka.krizove_dny[0] is False  # 1.8. - denní i noční na maximu
    assert mrizka.krizove_dny[1] is True  # 2.8. - denní plné, ale noční pod maximem


def test_sestavit_mrizku_souhrn_pocita_d_n_vikend(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    # 1.8.2026 je sobota (víkend) - D tuhle sobotu, N v pondělí (ne víkend)
    schedule = Schedule(rok=2026, mesic=8, jmena=("Alena",),
                         smeny={("Alena", 1): "D", ("Alena", 3): "N"},
                         status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    radek = mrizka.radky[0]
    assert radek.pocet_d == 1
    assert radek.pocet_n == 1
    assert radek.pocet_vikendu == 1  # jen 1.8. (sobota) se počítá


def test_sestavit_mrizku_dov_nem_ost_maji_rozdilne_tridy(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 3), "DOV")
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 4), date(2026, 8, 4), "NEM")
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "OST")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    radek = mrizka.radky[0]
    bunka_dov = radek.bunky[2]  # 3.8. (0-indexováno)
    bunka_nem = radek.bunky[3]  # 4.8.
    bunka_ost = radek.bunky[4]  # 5.8.

    assert bunka_dov.nedostupnost == "DOV"
    assert bunka_dov.trida == "nedostupnost-dov"
    assert bunka_dov.text == ""  # DOV se jen barví, bez textu (jako v PDF)

    # NEM má vlastní pastelovou třídu (na přání - snáz se v mřížce najde,
    # kdo je nemocný) a stejně jako DOV žádný text, jen barvu.
    # OST/POZADAVEK sdílí neutrální nedostupnost-jina a mají text.
    assert bunka_nem.nedostupnost == "NEM"
    assert bunka_nem.trida == "nedostupnost-nem"
    assert bunka_nem.text == ""

    assert bunka_ost.nedostupnost == "OST"
    assert bunka_ost.trida == "nedostupnost-jina"
    assert bunka_ost.text == "ost"


def test_sestavit_mrizku_pozadavek_se_zkrati_na_poz(conn):
    # POZADAVEK je jediný typ delší než 3 znaky - v buňce by přetékal a
    # překrýval sousední (viz nález), musí se zkrátit stejně jako v legendě
    # (a malými písmeny, ať v buňce opticky nekřičí přes D/N)
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "POZADAVEK")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    bunka = mrizka.radky[0].bunky[4]  # 5.8.

    assert bunka.nedostupnost == "POZADAVEK"
    assert bunka.text == "poz"
    assert bunka.nazev_nedostupnosti == "Požadavek"


def test_sestavit_mrizku_poznamka_jen_kdyz_je_admin(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 3), date(2026, 8, 3), "OST", poznamka="soukromý důvod"
    )

    mrizka_admin = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka_admin.radky[0].bunky[2].poznamka == "soukromý důvod"

    mrizka_nahled = sestavit_mrizku(conn, 2026, 8, je_admin=False)
    assert mrizka_nahled.radky[0].bunky[2].poznamka is None
    assert mrizka_nahled.radky[0].bunky[2].nedostupnost == "OST"  # typ ano, poznámka ne


def test_sestavit_mrizku_vikendy_odpovidaji_dnum(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    # srpen 2026: 1. a 2. je So/Ne
    assert mrizka.vikendy[0] is True
    assert mrizka.vikendy[1] is True
    assert mrizka.vikendy[2] is False
    assert mrizka.dny_tydne[0] == "So"


# --- úkol 8: zamčené buňky + porušení tvrdých pravidel ---

def test_sestavit_mrizku_zamestnanec_id_vyplneny(conn):
    id_alena, _ = _ulozit_zakladni_rozpis(conn)
    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].zamestnanec_id == id_alena


def test_sestavit_mrizku_zamcena_bunka(conn):
    _ulozit_zakladni_rozpis(conn)
    smena_id = repo.smeny_v_mesici(conn, 2026, 8)[0].id
    repo.zamknout_smeny(conn, [smena_id])

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    alena = mrizka.radky[0]
    assert alena.bunky[0].zamcena is True
    assert alena.bunky[1].zamcena is False


def test_sestavit_mrizku_duvod_poruseni_n_pak_d(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "N", ("Alena", 2): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    bunka_den_2 = mrizka.radky[0].bunky[1]
    assert bunka_den_2.duvod_poruseni is not None
    assert "po noční" in bunka_den_2.duvod_poruseni


def test_sestavit_mrizku_bez_poruseni_je_none(conn):
    _ulozit_zakladni_rozpis(conn)
    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].bunky[0].duvod_poruseni is None


def test_sestavit_mrizku_varovani_fond_pres_limit(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.ulozit_nastaveni(conn, NastaveniProfilu(
        profil="normalni", denni_min=0, denni_max=99, nocni_min=0, nocni_max=99,
        max_v_rade=99, max_smen_mesic=1,
    ))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D", ("Alena", 3): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].varovani
    assert "strop" in mrizka.radky[0].varovani[0]


def test_sestavit_mrizku_dny_s_porusenim_pod_minimem(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.ulozit_nastaveni(conn, NastaveniProfilu(
        profil="normalni", denni_min=2, denni_max=4, nocni_min=0, nocni_max=99,
        max_v_rade=99, max_smen_mesic=99,
    ))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.dny_s_porusenim[0] is True  # jen 1 denní, min je 2


# --- úkol 9: editovatelnost buňky (klikací cyklus D/N/volno/DOV/OST/NEM) ---

def test_sestavit_mrizku_prazdna_bunka_je_editovatelna(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].bunky[0].editovatelna is True


def test_sestavit_mrizku_zamcena_bunka_neni_editovatelna(conn):
    _ulozit_zakladni_rozpis(conn)
    smena_id = repo.smeny_v_mesici(conn, 2026, 8)[0].id
    repo.zamknout_smeny(conn, [smena_id])

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].bunky[0].editovatelna is False


def test_sestavit_mrizku_jednodenni_dov_je_editovatelna(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "DOV")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].bunky[4].editovatelna is True  # 5.8. = index 4


def test_sestavit_mrizku_vicedenni_dov_neni_editovatelna(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 7), "DOV")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].bunky[4].editovatelna is False  # 5.8.
    assert mrizka.radky[0].bunky[5].editovatelna is False  # 6.8.
    assert mrizka.radky[0].bunky[6].editovatelna is False  # 7.8.
    assert mrizka.radky[0].bunky[7].editovatelna is True  # 8.8. - mimo rozsah


def test_sestavit_mrizku_svz_neni_editovatelna(conn):
    # SVZ (školení v zařízení) není v cyklu buňky - i jednodenní záznam
    # se zadává jen přes /admin/nedostupnosti
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "SVZ")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    assert mrizka.radky[0].bunky[4].editovatelna is False


# --- sestavit_pozadavky_widget (úkol 9d: kalendářové widgety požadavků) ---

def test_widget_ukazuje_polozky_bez_ohledu_na_typ_a_stav(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "DOV")
    repo.pridat_pozadavek(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "chřipka", typ="NEM")

    dny = sestavit_pozadavky_widget(conn, 2026, 8)
    den5 = dny[4]
    assert den5.den == 5
    assert {p.stav for p in den5.polozky} == {"schvaleno", "podano"}
    assert {p.typ_nazev for p in den5.polozky} == {"Dovolená", "Nemoc"}


def test_widget_po_zamitnuti_den_vypada_volny(conn):
    # Zamítnutí záznam maže (žádný audit trail) - den se ve widgetu
    # vrátí do stavu, jako by požadavek nikdy nebyl podán.
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    poz_id = repo.pridat_pozadavek(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "x")
    repo.zamitnout_pozadavek(conn, poz_id)

    dny = sestavit_pozadavky_widget(conn, 2026, 8)
    den5 = dny[4]
    assert len(den5.polozky) == 0
    assert den5.volnych_pri_schvaleni == 1


def test_widget_castecny_den_nesnizuje_dostupnost(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 5), date(2026, 8, 5), "POZADAVEK", zakazana_smena="N"
    )

    dny = sestavit_pozadavky_widget(conn, 2026, 8)
    assert dny[4].volnych_pri_schvaleni == 1


def test_widget_riziko_pod_minimem(conn):
    id_a = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bara", date(2020, 1, 1))
    repo.ulozit_nastaveni(
        conn,
        NastaveniProfilu(
            profil="normalni", denni_min=1, denni_max=2, nocni_min=1, nocni_max=2,
            max_v_rade=3, max_smen_mesic=16,
        ),
    )
    repo.pridat_nedostupnost(conn, id_a, date(2026, 8, 5), date(2026, 8, 5), "DOV")

    dny = sestavit_pozadavky_widget(conn, 2026, 8)
    den5 = dny[4]
    assert den5.minimum == 2
    assert den5.volnych_pri_schvaleni == 1
    assert den5.riziko is True
    assert dny[5].riziko is False  # den bez nedostupnosti - 2 volní, na hraně minima


# --- HTTP vrstva: role a měsíc (viz zadani-faze3-web.md, úkol 3) ---

@pytest.fixture
def klient(tmp_path):
    cesta_db = tmp_path / "test.db"
    conn = repo.pripojit_a_inicializovat(cesta_db)
    repo.vytvorit_uzivatele(conn, "admin", hashovat_heslo("tajneheslo"), "admin")
    repo.vytvorit_uzivatele(conn, "nahled", hashovat_heslo("tajneheslo2"), "nahled")
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 3), date(2026, 8, 3), "OST", poznamka="tajna-poznamka-xyz"
    )
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 12), date(2026, 8, 12), "POZADAVEK")
    conn.close()

    app.state.cesta_db = cesta_db
    app.state.tajny_klic = "test-tajny-klic-neni-tajny"
    with TestClient(app, base_url="https://testserver") as klient:
        yield klient


def _prihlasit(klient, jmeno, heslo):
    klient.post("/login", data={"jmeno": jmeno, "heslo": heslo})


def test_korenova_stranka_presmeruje_na_rozpis(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/", follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/rozpis"


def test_admin_muze_zobrazit_libovolny_mesic(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2020-01")
    assert odpoved.status_code == 200
    assert "01/2020" in odpoved.text


def test_nahled_smi_listovat_libovolny_mesic(klient):
    # na přání zrušeno omezení "jen aktuální měsíc" (viz STAV-FAZE3.md) -
    # nahled navigaci teď má stejně jako admin.
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved = klient.get("/rozpis?mesic=2020-01")
    assert odpoved.status_code == 200
    assert "01/2020" in odpoved.text


def test_nahled_nevidi_poznamku_admin_ano(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved_admin = klient.get("/rozpis?mesic=2026-08")
    assert "tajna-poznamka-xyz" in odpoved_admin.text

    klient.post("/logout")
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved_nahled = klient.get("/rozpis")
    assert "tajna-poznamka-xyz" not in odpoved_nahled.text


def test_nahled_ma_navigaci_na_jiny_mesic(klient):
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved = klient.get("/rozpis")
    assert "předchozí" in odpoved.text
    assert "další" in odpoved.text


def test_admin_ma_navigaci_na_jiny_mesic(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis")
    assert "předchozí" in odpoved.text
    assert "další" in odpoved.text


# --- widgety požadavků pod mřížkou (úkol 9d) ---

def test_nahled_vidi_prehled_pozadavku_ale_ne_hromadne_schvaleni(klient):
    # úkol 9d rozšíření: nahled vidí read-only "Přehled požadavků" (stejný
    # kalendář jako admin), jen bez tlačítka na hromadné schválení -
    # jednotlivé schválit/zamítnout formuláře se navíc renderují až v JS
    # podle JE_ADMIN, takže v syrovém HTML nejsou ani pro admina.
    _prihlasit(klient, "nahled", "tajneheslo2")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert 'id="kalendar-podat"' in odpoved.text
    assert 'id="kalendar-sprava"' in odpoved.text
    assert "Přehled požadavků" in odpoved.text
    assert "Schválit nekonfliktní" not in odpoved.text


def test_admin_vidi_oba_widgety(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert 'id="kalendar-podat"' in odpoved.text
    assert 'id="kalendar-sprava"' in odpoved.text
    assert "Schválit nekonfliktní" in odpoved.text


def test_rozpis_nema_odkaz_na_samostatnou_stranku_pozadavku(klient):
    # úkol 9d: "žádné menu" - požadavky žijí jako widget pod mřížkou,
    # ne jako samostatná položka v navigaci (na rozdíl od Rozpis/Přepis).
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    nav_html = odpoved.text.split('<nav class="nav">')[1].split("</nav>")[0]
    assert "/pozadavky" not in nav_html


def test_rozpis_zkracuje_pozadavek_na_poz(klient):
    # nález: POZADAVEK se dřív vypisoval celý a přetékal mimo buňku;
    # zkratka je navíc malými písmeny (poz), ať v buňce nekřičí přes D/N.
    # Mimo mřížku (úkol 9d: select typu ve widgetu Podat požadavek) se
    # kód POZADAVEK jako hodnota <option> objevit smí - kontrola se proto
    # omezuje jen na samotnou tabulku mřížky.
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    mrizka_html = odpoved.text.split('<div class="mrizka-obal">')[1].split("</table>")[0]
    assert ">poz<" in mrizka_html
    assert "POZADAVEK" not in mrizka_html
    assert 'title="Požadavek"' in mrizka_html


def test_rozpis_zobrazuje_radek_obsazeni(klient):
    _prihlasit(klient, "admin", "tajneheslo")
    odpoved = klient.get("/rozpis?mesic=2026-08")
    assert "Obsazení" in odpoved.text


def test_rozpis_bez_loginu_presmeruje_na_login(klient):
    odpoved = klient.get("/rozpis", follow_redirects=False)
    assert odpoved.status_code == 303
    assert odpoved.headers["location"] == "/login"
