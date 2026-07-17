"""Testy datové vrstvy nad SQLite (fáze 2)."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from db import repository as repo
from db.bridge import config_pro_mesic, schedule_z_db, souhrn_vstupu
from db.models import NastaveniProfilu
from solver.core import generate_schedule
from solver.schedule import Schedule

ZBYVAJICI_11 = [
    "Bedřich", "Cyril", "Dana", "Emil", "Frantiska", "Gustav",
    "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]


@pytest.fixture
def conn():
    connection = repo.pripojit(":memory:")
    repo.inicializovat_schema(connection)
    yield connection
    connection.close()


def test_pridat_a_vypsat_aktivni_zamestnance(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(
        conn, "Bedřich", date(2020, 1, 1), stitky=["fyzicka_vypomoc"]
    )

    aktivni = repo.aktivni_zamestnanci(conn, date(2026, 1, 1))
    jmena = {z.jmeno for z in aktivni}
    assert jmena == {"Alena", "Bedřich"}

    bedrich = next(z for z in aktivni if z.id == id_b)
    assert bedrich.stitky == "fyzicka_vypomoc"
    assert bedrich.seznam_stitku == ["fyzicka_vypomoc"]


def test_zakaz_smeny_a_max_za_sebou_vychozi_none(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    alena = repo.aktivni_zamestnanci(conn, date(2026, 1, 1))[0]
    assert alena.id == id_
    assert alena.zakaz_smeny is None
    assert alena.max_za_sebou is None


def test_nastavit_zakaz_smeny_a_max_za_sebou(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))

    repo.nastavit_zakaz_smeny(conn, id_, "N")
    repo.nastavit_max_za_sebou(conn, id_, 1)

    alena = repo.aktivni_zamestnanci(conn, date(2026, 1, 1))[0]
    assert alena.zakaz_smeny == "N"
    assert alena.max_za_sebou == 1

    # zrušení zpět na None (konec zdravotního omezení apod.)
    repo.nastavit_zakaz_smeny(conn, id_, None)
    repo.nastavit_max_za_sebou(conn, id_, None)
    alena = repo.aktivni_zamestnanci(conn, date(2026, 1, 1))[0]
    assert alena.zakaz_smeny is None
    assert alena.max_za_sebou is None


def test_zakaz_smeny_odmita_neplatnou_hodnotu(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    with pytest.raises(sqlite3.IntegrityError):
        repo.nastavit_zakaz_smeny(conn, id_, "X")


def test_deaktivovany_zamestnanec_zmizi_po_datu_odchodu(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 6, 30))

    aktivni_pred = repo.aktivni_zamestnanci(conn, date(2026, 6, 15))
    assert id_ in {z.id for z in aktivni_pred}

    aktivni_v_den_odchodu = repo.aktivni_zamestnanci(conn, date(2026, 6, 30))
    assert id_ in {z.id for z in aktivni_v_den_odchodu}  # aktivni_do je včetně


def test_deaktivovat_zamestnance_pred_nastupem_vyhodi_value_error(conn):
    """Audit: aktivni_do před aktivni_od by zaměstnance potichu vyřadilo
    ze VŠECH "aktivní" dotazů (i zpětně) - žádné datum by nesplnilo
    aktivni_od <= datum <= aktivni_do zároveň."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2026, 6, 1))
    with pytest.raises(ValueError, match="nástupem"):
        repo.deaktivovat_zamestnance(conn, id_, date(2026, 5, 1))

    # neúspěšná deaktivace nesmí zaměstnance poškodit - pořád aktivní
    aktivni = repo.aktivni_zamestnanci(conn, date(2026, 6, 15))
    assert id_ in {z.id for z in aktivni}


def test_deaktivovat_zamestnance_v_den_nastupu_projde(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2026, 6, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 6, 1))
    aktivni = repo.aktivni_zamestnanci(conn, date(2026, 6, 1))
    assert id_ in {z.id for z in aktivni}


def test_zamestnanec_podle_id(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    assert repo.zamestnanec_podle_id(conn, id_).jmeno == "Alena"
    assert repo.zamestnanec_podle_id(conn, id_ + 999) is None


def test_deaktivace_zachova_historii_smen(conn):
    """Úkol 4: deaktivace nesmí smazat/skrýt uložené směny - historie
    rozpisů musí zůstat konzistentní i pro bývalého zaměstnance."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    repo.deaktivovat_zamestnance(conn, id_, date(2026, 6, 30))

    smeny = repo.smeny_v_mesici(conn, 2026, 8)
    assert any(s.zamestnanec_id == id_ and s.typ == "D" for s in smeny)


def test_ma_nejakou_smenu(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    assert repo.ma_nejakou_smenu(conn, id_) is False

    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    assert repo.ma_nejakou_smenu(conn, id_) is True


def test_smazat_zamestnance_bez_smeny_smaze_zaznam(conn):
    """Tvrdé smazání jen pro omyl při zakládání - záznam bez jediné
    směny smí zmizet úplně (na rozdíl od deaktivace)."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.smazat_zamestnance(conn, id_)
    assert repo.zamestnanec_podle_id(conn, id_) is None


def test_smazat_zamestnance_se_smenou_selze(conn):
    """Zaměstnanec s historií se NIKDY nemaže (viz CLAUDE.md) - jen
    deaktivuje. Cizí klíč (smena.zamestnanec_id) smazání zablokuje."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    with pytest.raises(ValueError, match="nejde smazat"):
        repo.smazat_zamestnance(conn, id_)
    assert repo.zamestnanec_podle_id(conn, id_) is not None

    # zaměstnanec se nikdy nemaže - historicky zůstává v DB
    radek = conn.execute("SELECT * FROM zamestnanec WHERE id = ?", (id_,)).fetchone()
    assert radek is not None
    assert radek["jmeno"] == "Alena"


def test_opravit_jmeno_zamestnance(conn):
    id_ = repo.pridat_zamestnance(conn, "Adamcová Bezemková Andrea", date(2020, 1, 1))
    repo.opravit_jmeno_zamestnance(conn, id_, "Bezemková Andrea")

    aktivni = repo.aktivni_zamestnanci(conn, date(2026, 1, 1))
    opravena = next(z for z in aktivni if z.id == id_)
    assert opravena.jmeno == "Bezemková Andrea"


def test_prekryv_nedostupnosti_stejneho_zamestnance(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    # dovolená 3.-9. srpna, uprostřed toho nahlášená nemoc 5.-7. (překryv)
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 7), "NEM")

    # v DB zůstávají obě položky zvlášť (typ/poznámka se neztrácí)
    nedostupnosti = repo.nedostupnosti_v_obdobi(conn, date(2026, 8, 1), date(2026, 8, 31))
    assert len(nedostupnosti) == 2

    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    dny_alena = config.nedostupnosti["Alena"]
    # sjednocení překrývajících se intervalů - žádná duplicita, žádný den navíc
    assert sorted(dny_alena) == [3, 4, 5, 6, 7, 8, 9]
    assert len(dny_alena) == len(set(dny_alena))


def test_interval_pres_hranici_mesice_zasahne_oba_mesice(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    # dovolená 28.7.-5.8.2026
    repo.pridat_nedostupnost(conn, id_, date(2026, 7, 28), date(2026, 8, 5), "DOV")
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config_cervenec = config_pro_mesic(conn, 2026, 7)
    config_srpen = config_pro_mesic(conn, 2026, 8)

    assert sorted(config_cervenec.nedostupnosti["Alena"]) == [28, 29, 30, 31]
    assert sorted(config_srpen.nedostupnosti["Alena"]) == [1, 2, 3, 4, 5]


def test_max_smen_mesic_se_projevi_v_configu_pro_mesic(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1), max_smen_mesic=5)
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    assert config.max_smen_mesic_override == {"Alena": 5}


def test_nastavit_max_smen_mesic_zmeni_existujiciho_zamestnance(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config_pred = config_pro_mesic(conn, 2026, 8)
    assert config_pred.max_smen_mesic_override == {}

    repo.nastavit_max_smen_mesic(conn, id_, 10)
    config_po = config_pro_mesic(conn, 2026, 8)
    assert config_po.max_smen_mesic_override == {"Alena": 10}


def test_max_smen_mesic_z_db_ovlivni_vygenerovany_rozpis(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1), max_smen_mesic=5)
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)
    assert schedule.souhrn_zamestnance("Alena")["smeny"] <= 5


def test_zakaz_smeny_se_projevi_v_configu_pro_cely_mesic(conn):
    # trvalé osobní omezení (na rozdíl od nedostupnost.zakazana_smena)
    # musí platit pro VŠECHNY dny měsíce, ne jen jeden interval
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.nastavit_zakaz_smeny(conn, id_, "N")
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    assert set(config.zakazane_smeny["Alena"].keys()) == set(range(1, 32))
    assert all(typy == ("N",) for typy in config.zakazane_smeny["Alena"].values())


def test_max_za_sebou_se_projevi_v_configu_pro_mesic(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.nastavit_max_za_sebou(conn, id_, 1)
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    assert config.max_v_rade_override == {"Alena": 1}


def test_zakaz_smeny_a_max_za_sebou_z_db_ovlivni_vygenerovany_rozpis(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.nastavit_zakaz_smeny(conn, id_, "N")
    repo.nastavit_max_za_sebou(conn, id_, 1)
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0, random_seed=42)

    for den in range(1, schedule.pocet_dni + 1):
        assert schedule.smena_zamestnance("Alena", den) != "N"
    for den in range(1, schedule.pocet_dni):
        pracuje_dnes = schedule.smena_zamestnance("Alena", den) is not None
        pracuje_zitra = schedule.smena_zamestnance("Alena", den + 1) is not None
        assert not (pracuje_dnes and pracuje_zitra)


def test_odchod_uprostred_mesice_omezi_dostupnost_jen_na_aktivni_dny(conn):
    # brigádnice odchází 15.8. uprostřed měsíce - aktivni_zamestnanci_v_obdobi
    # ji do configu pro srpen pořád zahrne (interval se s měsícem překrývá),
    # ale nesmí zůstat "dostupná" i po dnech, kdy už fakticky neexistuje
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 8, 15))
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    assert "Alena" in config.jmena
    dny_po_odchodu = set(range(16, 32))
    assert dny_po_odchodu <= set(config.nedostupnosti["Alena"])
    assert 15 not in config.nedostupnosti["Alena"]  # poslední den ještě aktivní


def test_nastup_uprostred_mesice_omezi_dostupnost_az_od_nastupu(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2026, 8, 10))
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    dny_pred_nastupem = set(range(1, 10))
    assert dny_pred_nastupem <= set(config.nedostupnosti["Alena"])
    assert 10 not in config.nedostupnosti["Alena"]  # den nástupu už aktivní


def test_odchod_uprostred_mesice_se_projevi_ve_vygenerovanem_rozpisu(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 8, 15))
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)
    for den in range(16, 32):
        assert schedule.smena_zamestnance("Alena", den) is None


def test_deaktivovany_zamestnanec_neni_v_configu_pro_mesic(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 6, 30))
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config_cerven = config_pro_mesic(conn, 2026, 6)  # Alena aktivní do 30.6.
    config_srpen = config_pro_mesic(conn, 2026, 8)   # Alena už neaktivní

    assert "Alena" in config_cerven.jmena
    assert "Alena" not in config_srpen.jmena


def test_nedostupnost_deaktivovaneho_zamestnance_se_ignoruje(conn):
    # nedostupnost zůstává v DB, ale pokud zaměstnanec v daném měsíci už
    # není aktivní, nesmí se objevit v configu (byl by to odkaz na "ducha")
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 6, 30))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config_srpen = config_pro_mesic(conn, 2026, 8)
    assert "Alena" not in config_srpen.nedostupnosti


def test_zakazana_smena_se_neprojevi_jako_celodenni_nedostupnost(conn):
    # "ne denní směnu" (zakazana_smena='D') musí skončit v config.zakazane_smeny,
    # ne v config.nedostupnosti (tam by ji to vyřadilo z celého dne)
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 21), date(2026, 8, 21), "POZADAVEK",
        poznamka="ne denní směnu", zakazana_smena="D",
    )
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    assert "Alena" not in config.nedostupnosti
    assert config.zakazane_smeny["Alena"][21] == ("D",)


def test_zakazana_smena_z_db_ovlivni_vygenerovany_rozpis(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 21), date(2026, 8, 21), "POZADAVEK",
        zakazana_smena="D",
    )
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)
    assert schedule.smena_zamestnance("Alena", 21) != "D"


def test_dvojice_se_prevedou_na_jmena_v_configu(conn):
    id_a = repo.pridat_zamestnance(conn, "Cyril", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(conn, "Karel", date(2020, 1, 1))
    for jmeno in ["Alena", "Bedřich", "Dana", "Emil", "Frantiska",
                  "Gustav", "Hana", "Ivan", "Jitka", "Lenka"]:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.pridat_dvojici(conn, id_a, id_b)

    config = config_pro_mesic(conn, 2026, 8)
    assert ("Cyril", "Karel") in config.nekompatibilni_dvojice


def test_pridat_a_vypsat_dvojici(conn):
    id_a = repo.pridat_zamestnance(conn, "Cyril", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(conn, "Karel", date(2020, 1, 1))
    repo.pridat_dvojici(conn, id_a, id_b)

    vsechny = repo.dvojice_vsechny(conn)
    assert len(vsechny) == 1
    d = vsechny[0]
    assert (d.zamestnanec_a_id, d.zamestnanec_b_id) == (id_a, id_b)
    assert d.typ == "rozprostrit"  # výchozí hodnota, nebylo zadáno explicitně


def test_dvojice_s_neaktivnim_clenem_se_v_mesici_ignoruje(conn):
    # Karel odejde koncem června - dvojice zůstává v DB (nikdy se
    # nemaže), ale pro měsíc, kdy už není aktivní, nedává smysl ji
    # promítat do configu (byl by to odkaz na "ducha", stejně jako
    # u nedostupností neaktivního zaměstnance)
    id_a = repo.pridat_zamestnance(conn, "Cyril", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(conn, "Karel", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_b, date(2026, 6, 30))
    for jmeno in ["Alena", "Bedřich", "Dana", "Emil", "Frantiska",
                  "Gustav", "Hana", "Ivan", "Jitka", "Lenka"]:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.pridat_dvojici(conn, id_a, id_b)

    config_cerven = config_pro_mesic(conn, 2026, 6)  # Karel ještě aktivní
    config_srpen = config_pro_mesic(conn, 2026, 8)   # Karel už neaktivní

    assert ("Cyril", "Karel") in config_cerven.nekompatibilni_dvojice
    assert config_srpen.nekompatibilni_dvojice == ()


def test_zakazana_dvojice_se_prevede_zvlast_od_nekompatibilni(conn):
    id_a = repo.pridat_zamestnance(conn, "Holfaier", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(conn, "Stloukal", date(2020, 1, 1))
    for jmeno in ["Alena", "Bedřich", "Cyril", "Dana", "Emil", "Frantiska",
                  "Gustav", "Hana", "Ivan", "Jitka"]:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.pridat_dvojici(conn, id_a, id_b, typ="zakazano")

    config = config_pro_mesic(conn, 2026, 8)
    assert ("Holfaier", "Stloukal") in config.zakazane_dvojice
    assert config.nekompatibilni_dvojice == ()


def test_zakazana_dvojice_z_db_ovlivni_vygenerovany_rozpis(conn):
    id_a = repo.pridat_zamestnance(conn, "Holfaier", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(conn, "Stloukal", date(2020, 1, 1))
    for jmeno in ["Alena", "Bedřich", "Cyril", "Dana", "Emil", "Frantiska",
                  "Gustav", "Hana", "Ivan", "Jitka"]:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.pridat_dvojici(conn, id_a, id_b, typ="zakazano")

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)
    for den in range(1, schedule.pocet_dni + 1):
        s_a = schedule.smena_zamestnance("Holfaier", den)
        s_b = schedule.smena_zamestnance("Stloukal", den)
        if s_a is not None and s_b is not None:
            assert s_a != s_b


def test_dvojice_z_db_ovlivni_vygenerovany_rozpis(conn):
    # end-to-end: dvojice zadaná přes DB musí reálně ovlivnit chování
    # solveru, ne jen projít konverzí na jména v configu (to už ověřuje
    # test_dvojice_se_prevedou_na_jmena_v_configu výše)
    id_a = repo.pridat_zamestnance(conn, "Cyril", date(2020, 1, 1))
    id_b = repo.pridat_zamestnance(conn, "Karel", date(2020, 1, 1))
    for jmeno in ["Alena", "Bedřich", "Dana", "Emil", "Frantiska",
                  "Gustav", "Hana", "Ivan", "Jitka", "Lenka"]:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.pridat_dvojici(conn, id_a, id_b)

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)

    for den in range(1, schedule.pocet_dni + 1):
        smena_cyril = schedule.smena_zamestnance("Cyril", den)
        smena_karel = schedule.smena_zamestnance("Karel", den)
        if smena_cyril is not None and smena_karel is not None:
            assert smena_cyril != smena_karel, (
                f"den {den}: Cyril i Karel slouží stejnou směnu, ačkoli "
                "jsou v DB zadaní jako neslučitelná dvojice"
            )


def test_vytvorit_uzivatele_a_najit_podle_jmena_i_id(conn):
    id_ = repo.vytvorit_uzivatele(conn, "vedouci", "hash123", "admin")

    podle_jmena = repo.uzivatel_podle_jmena(conn, "vedouci")
    assert podle_jmena is not None
    assert podle_jmena.id == id_
    assert podle_jmena.role == "admin"
    assert podle_jmena.heslo_hash == "hash123"

    podle_id = repo.uzivatel_podle_id(conn, id_)
    assert podle_id == podle_jmena


def test_uzivatel_podle_jmena_neexistujici_vraci_none(conn):
    assert repo.uzivatel_podle_jmena(conn, "neznamy") is None


def test_zmenit_heslo(conn):
    id_ = repo.vytvorit_uzivatele(conn, "vedouci", "puvodni_hash", "nahled")
    repo.zmenit_heslo(conn, id_, "novy_hash")

    assert repo.uzivatel_podle_id(conn, id_).heslo_hash == "novy_hash"


def test_uzivatel_role_musi_byt_admin_nebo_nahled(conn):
    with pytest.raises(sqlite3.IntegrityError):
        repo.vytvorit_uzivatele(conn, "spatna_role", "hash", "superadmin")


def test_ulozit_rozpis_zapise_smeny(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    id_bedrich = repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))

    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
        smeny={("Alena", 1): "D", ("Bedřich", 1): "N", ("Alena", 2): "D"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    smeny = {(s.zamestnanec_id, s.datum): s.typ for s in repo.smeny_v_mesici(conn, 2026, 8)}
    assert smeny == {
        (id_alena, date(2026, 8, 1)): "D",
        (id_bedrich, date(2026, 8, 1)): "N",
        (id_alena, date(2026, 8, 2)): "D",
    }


def test_ulozit_rozpis_prepise_nezamcene_pri_dalsim_volani(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    prvni = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                      status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, prvni)

    druhy = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "N"},
                      status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, druhy)

    smeny = repo.smeny_v_mesici(conn, 2026, 8)
    assert len(smeny) == 1
    assert smeny[0].typ == "N"


def test_ulozit_rozpis_nikdy_neprepise_zamcenou_smenu(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    puvodni = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                        status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, puvodni)

    zamcena = repo.smeny_v_mesici(conn, 2026, 8)[0]
    repo.zamknout_smeny(conn, [zamcena.id])

    novy = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "N"},
                     status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, novy)

    smeny = repo.smeny_v_mesici(conn, 2026, 8)
    assert len(smeny) == 1
    assert smeny[0].typ == "D"  # zůstala původní, ne přepsaná na N z nového rozpisu
    assert smeny[0].locked is True


def test_ulozit_rozpis_konflikt_se_zamcenou_smenou_vraci_info_a_neprepise(conn):
    # stejný scénář jako test výše (stejný zaměstnanec+datum, jiný typ),
    # ale tady ověřujeme i návratovou hodnotu ulozit_rozpis - volající
    # (web/CLI) potřebuje vědět, které konflikty se tiše zahodily.
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))

    puvodni = Schedule(rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
                        smeny={("Alena", 1): "D", ("Bedřich", 1): "N"},
                        status="OPTIMAL", cas_reseni=0.1)
    preskocene_prvni = repo.ulozit_rozpis(conn, puvodni)
    assert preskocene_prvni == []  # bez zamčených směn žádný konflikt nemůže nastat

    zamcena = next(s for s in repo.smeny_v_mesici(conn, 2026, 8) if s.zamestnanec_id == id_alena)
    repo.zamknout_smeny(conn, [zamcena.id])

    # nový rozpis navrhuje pro Alenu 1.8. noční (kolize) a pro Bedřicha
    # stejnou nezamčenou noční jako předtím (žádná kolize, ta se prostě
    # smaže a zapíše znovu)
    novy = Schedule(rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
                     smeny={("Alena", 1): "N", ("Bedřich", 1): "N"},
                     status="OPTIMAL", cas_reseni=0.1)
    preskocene = repo.ulozit_rozpis(conn, novy)

    assert len(preskocene) == 1
    konflikt = preskocene[0]
    assert konflikt.zamestnanec_id == id_alena
    assert konflikt.jmeno == "Alena"
    assert konflikt.datum == date(2026, 8, 1)
    assert konflikt.puvodni_typ == "D"
    assert konflikt.novy_typ == "N"

    # a DB skutečně odpovídá "locked vyhrává"
    smeny = repo.smeny_v_mesici(conn, 2026, 8)
    typ_podle_zamestnance = {s.zamestnanec_id: s.typ for s in smeny}
    assert typ_podle_zamestnance[id_alena] == "D"


def test_ulozit_rozpis_stejny_typ_jako_zamcena_smena_neni_konflikt(conn):
    # pokud nový rozpis pro zamčený den navrhuje STEJNÝ typ, jde o no-op,
    # ne o konflikt hodný nahlášení
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    puvodni = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                        status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, puvodni)
    zamcena = repo.smeny_v_mesici(conn, 2026, 8)[0]
    repo.zamknout_smeny(conn, [zamcena.id])

    stejny = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                       status="OPTIMAL", cas_reseni=0.1)
    preskocene = repo.ulozit_rozpis(conn, stejny)

    assert preskocene == []
    smena = repo.smeny_v_mesici(conn, 2026, 8)[0]
    assert smena.zamestnanec_id == id_alena
    assert smena.typ == "D"


def test_ulozit_rozpis_je_atomicka_pri_chybe_se_nic_neulozi(conn):
    # smena.typ má CHECK IN ('D', 'N') - "X" vyhodí IntegrityError uprostřed
    # zápisu. Ověřujeme, že celá operace je jedna transakce: ani zamčená
    # směna, ani nic z nezamčených nových směn se nepropíše.
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))

    puvodni = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                        status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, puvodni)
    zamcena = repo.smeny_v_mesici(conn, 2026, 8)[0]
    repo.zamknout_smeny(conn, [zamcena.id])

    # pořadí v dict je insertion-order (Python 3.7+) - "Alena" je validní
    # a zapsala by se první, "Bedřich" s neplatným typem shodí transakci
    vadny = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
        smeny={("Alena", 2): "D", ("Bedřich", 1): "X"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.ulozit_rozpis(conn, vadny)

    # DB je přesně tam, kde byla před neúspěšným voláním - žádná Alena 2.8.,
    # žádný Bedřich, zamčená směna z 1.8. netknutá
    smeny = repo.smeny_v_mesici(conn, 2026, 8)
    assert len(smeny) == 1
    assert smeny[0].zamestnanec_id == id_alena
    assert smeny[0].datum == date(2026, 8, 1)
    assert smeny[0].typ == "D"
    assert smeny[0].locked is True


def test_zamknout_a_odemknout_smeny(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                         status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, schedule)
    smena_id = repo.smeny_v_mesici(conn, 2026, 8)[0].id

    assert repo.smeny_v_mesici(conn, 2026, 8)[0].locked is False

    repo.zamknout_smeny(conn, [smena_id])
    assert repo.smeny_v_mesici(conn, 2026, 8)[0].locked is True

    repo.odemknout_smeny(conn, [smena_id])
    assert repo.smeny_v_mesici(conn, 2026, 8)[0].locked is False


def test_smena_pro_den(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    assert repo.smena_pro_den(conn, id_, date(2026, 8, 1)) is None

    schedule = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                         status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, schedule)
    assert repo.smena_pro_den(conn, id_, date(2026, 8, 1)).typ == "D"


def test_nastavit_smenu_vytvori_novou(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.nastavit_smenu(conn, id_, date(2026, 8, 1), "D")
    assert repo.smena_pro_den(conn, id_, date(2026, 8, 1)).typ == "D"


def test_nastavit_smenu_prepise_existujici(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.nastavit_smenu(conn, id_, date(2026, 8, 1), "D")
    repo.nastavit_smenu(conn, id_, date(2026, 8, 1), "N")
    assert repo.smena_pro_den(conn, id_, date(2026, 8, 1)).typ == "N"


def test_nastavit_smenu_s_none_smaze(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.nastavit_smenu(conn, id_, date(2026, 8, 1), "D")
    repo.nastavit_smenu(conn, id_, date(2026, 8, 1), None)
    assert repo.smena_pro_den(conn, id_, date(2026, 8, 1)) is None


def test_nastavit_smenu_zamcenou_vyhodi_value_error(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 1): "D"},
                         status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, schedule)
    smena_id = repo.smeny_v_mesici(conn, 2026, 8)[0].id
    repo.zamknout_smeny(conn, [smena_id])

    with pytest.raises(ValueError, match="zamčená"):
        repo.nastavit_smenu(conn, id_, date(2026, 8, 1), "N")
    assert repo.smena_pro_den(conn, id_, date(2026, 8, 1)).typ == "D"  # beze změny


def test_smazat_nezamcene_v_obdobi_zachova_zamcene(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D", ("Alena", 2): "N"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    id_prvniho = next(
        s.id for s in repo.smeny_v_mesici(conn, 2026, 8) if s.datum == date(2026, 8, 1)
    )
    repo.zamknout_smeny(conn, [id_prvniho])

    repo.smazat_nezamcene_v_obdobi(conn, date(2026, 8, 1), date(2026, 8, 31))

    zbyle = repo.smeny_v_mesici(conn, 2026, 8)
    assert len(zbyle) == 1
    assert zbyle[0].datum == date(2026, 8, 1)
    assert zbyle[0].locked is True


def test_smeny_v_mesici_neobsahuje_jiny_mesic(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    srpen = Schedule(rok=2026, mesic=8, jmena=("Alena",), smeny={("Alena", 31): "D"},
                      status="OPTIMAL", cas_reseni=0.1)
    zari = Schedule(rok=2026, mesic=9, jmena=("Alena",), smeny={("Alena", 1): "N"},
                     status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, srpen)
    repo.ulozit_rozpis(conn, zari)

    assert len(repo.smeny_v_mesici(conn, 2026, 8)) == 1
    assert len(repo.smeny_v_mesici(conn, 2026, 9)) == 1


def test_zrusit_nedostupnost(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")
    repo.zrusit_nedostupnost(conn, ned_id)

    assert repo.nedostupnosti_v_obdobi(conn, date(2026, 8, 1), date(2026, 8, 31)) == []


def test_nedostupnost_podle_id(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    ned = repo.nedostupnost_podle_id(conn, ned_id)
    assert ned.typ == "DOV"
    assert repo.nedostupnost_podle_id(conn, ned_id + 999) is None


def test_nedostupnost_typ_svz_projde(conn):
    """SVZ = školení v zařízení (úkol 5) - CHECK na nedostupnost.typ
    rozšířen, nesmí spadnout na IntegrityError."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 4), "SVZ")
    assert repo.nedostupnost_podle_id(conn, ned_id).typ == "SVZ"


def test_pridat_nedostupnost_obraceny_rozsah_vyhodi_value_error(conn):
    """Audit: obrácený rozsah (od > do) by se tiše uložil jako záznam,
    který ve skutečnosti nic neblokuje (dny_v_mesici na něm vrátí 0 dní)."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    with pytest.raises(ValueError, match="od.*do"):
        repo.pridat_nedostupnost(conn, id_, date(2026, 8, 9), date(2026, 8, 3), "DOV")
    assert repo.nedostupnosti_v_obdobi(conn, date(2026, 8, 1), date(2026, 8, 31)) == []


def test_pridat_nedostupnost_stejny_den_projde(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 3), "DOV")
    assert repo.nedostupnost_podle_id(conn, ned_id) is not None


def test_upravit_nedostupnost_obraceny_rozsah_vyhodi_value_error(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    with pytest.raises(ValueError, match="od.*do"):
        repo.upravit_nedostupnost(conn, ned_id, date(2026, 8, 9), date(2026, 8, 3), "DOV")

    # neúspěšná úprava nesmí poškodit původní záznam
    puvodni = repo.nedostupnost_podle_id(conn, ned_id)
    assert puvodni.od == date(2026, 8, 3)
    assert puvodni.do == date(2026, 8, 9)


def test_upravit_nedostupnost(conn):
    """Úkol 5: "doplnit editaci" - existující repo funkce uměly jen
    add/remove, teď i přepis na místě."""
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    repo.upravit_nedostupnost(
        conn, ned_id, date(2026, 8, 5), date(2026, 8, 6), "OST", poznamka="oprava"
    )

    ned = repo.nedostupnost_podle_id(conn, ned_id)
    assert ned.od == date(2026, 8, 5)
    assert ned.do == date(2026, 8, 6)
    assert ned.typ == "OST"
    assert ned.poznamka == "oprava"


def test_prekryvajici_nedostupnosti_najde_prekryv(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    prekryv = repo.prekryvajici_nedostupnosti(conn, id_, date(2026, 8, 8), date(2026, 8, 12))
    assert len(prekryv) == 1

    bez_prekryvu = repo.prekryvajici_nedostupnosti(conn, id_, date(2026, 8, 10), date(2026, 8, 12))
    assert bez_prekryvu == []


def test_prekryvajici_nedostupnosti_ignoruje_jineho_zamestnance(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    id_bedrich = repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_bedrich, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    prekryv = repo.prekryvajici_nedostupnosti(conn, id_alena, date(2026, 8, 3), date(2026, 8, 9))
    assert prekryv == []


def test_vsechny_nedostupnosti(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2020, 1, 3), date(2020, 1, 9), "DOV")
    repo.pridat_nedostupnost(conn, id_, date(2030, 1, 3), date(2030, 1, 9), "NEM")

    vsechny = repo.vsechny_nedostupnosti(conn)
    assert len(vsechny) == 2
    assert vsechny[0].od == date(2030, 1, 3)  # nejnovější první


def test_prekryvajici_nedostupnosti_vynecha_sebe_pri_editaci(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    prekryv = repo.prekryvajici_nedostupnosti(
        conn, id_, date(2026, 8, 3), date(2026, 8, 9), vynechat_id=ned_id
    )
    assert prekryv == []


def test_most_na_solver_end_to_end(conn):
    # stejná sestava 12 lidí jako v config.yaml, bez nedostupností -
    # ověřuje, že se DB stav dá reálně poslat do generate_schedule()
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    for jmeno in ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)

    assert schedule.pocet_dni == 31
    for den in range(1, schedule.pocet_dni + 1):
        pocet_d, pocet_n = schedule.obsazeni_dne(den)
        assert config.obsazeni.denni_min <= pocet_d <= config.obsazeni.denni_max
        assert pocet_n == 2


def test_schedule_z_db_sestavi_smeny_z_ulozeneho_rozpisu(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    puvodni = Schedule(rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
                        smeny={("Alena", 1): "D", ("Bedřich", 1): "N"},
                        status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, puvodni)

    schedule = schedule_z_db(conn, 2026, 8)
    assert schedule.status == "ULOZENO"
    assert set(schedule.jmena) == {"Alena", "Bedřich"}
    assert schedule.smena_zamestnance("Alena", 1) == "D"
    assert schedule.smena_zamestnance("Bedřich", 1) == "N"
    assert schedule.smena_zamestnance("Alena", 2) is None


def test_schedule_z_db_ma_zamcene_smeny(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    puvodni = Schedule(rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
                        smeny={("Alena", 1): "D", ("Bedřich", 1): "N"},
                        status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, puvodni)
    smena_alena_id = next(
        s.id for s in repo.smeny_v_mesici(conn, 2026, 8) if s.zamestnanec_id == id_alena
    )
    repo.zamknout_smeny(conn, [smena_alena_id])

    schedule = schedule_z_db(conn, 2026, 8)
    assert schedule.je_zamcena("Alena", 1) is True
    assert schedule.je_zamcena("Bedřich", 1) is False
    assert schedule.je_zamcena("Alena", 2) is False


def test_schedule_z_db_obsahuje_duvod_nedostupnosti(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 5), "DOV")

    schedule = schedule_z_db(conn, 2026, 8)
    assert schedule.duvod_nedostupnosti("Alena", 3) == "DOV"
    assert schedule.duvod_nedostupnosti("Alena", 5) == "DOV"
    assert schedule.duvod_nedostupnosti("Alena", 6) is None
    assert schedule.smena_zamestnance("Alena", 3) is None


def test_schedule_z_db_neaktivni_zamestnanec_se_neobjevi(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2025, 12, 31))

    schedule = schedule_z_db(conn, 2026, 8)
    assert "Alena" not in schedule.jmena


def test_schedule_z_db_orizne_nedostupnost_po_konci_pomeru(conn):
    # nález: starý záznam "ne noční směnu" zadaný na celý měsíc dřív, než
    # bylo jasné, že brigáda skončí uprostřed měsíce, nesmí "svítit" v
    # mřížce ještě po dnech, kdy zaměstnanec už fakticky neexistuje
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(
        conn, id_, date(2026, 8, 1), date(2026, 8, 31), "POZADAVEK", zakazana_smena="N",
    )
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 8, 16))

    schedule = schedule_z_db(conn, 2026, 8)
    assert schedule.duvod_nedostupnosti("Alena", 10) == "POZADAVEK"  # před odchodem platí
    assert schedule.duvod_nedostupnosti("Alena", 16) == "POZADAVEK"  # poslední den včetně
    assert schedule.duvod_nedostupnosti("Alena", 17) is None  # po odchodu už prázdné
    assert schedule.duvod_nedostupnosti("Alena", 31) is None


def test_schedule_z_db_orizne_nedostupnost_pred_nastupem(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2026, 8, 15))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 1), date(2026, 8, 31), "DOV")

    schedule = schedule_z_db(conn, 2026, 8)
    assert schedule.duvod_nedostupnosti("Alena", 10) is None  # před nástupem
    assert schedule.duvod_nedostupnosti("Alena", 20) == "DOV"


def test_souhrn_vstupu_pocita_zamestnance_a_nedostupnosti(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_alena, date(2026, 8, 3), date(2026, 8, 9), "DOV")

    pocet_zamestnancu, pocet_nedostupnosti = souhrn_vstupu(conn, 2026, 8)
    assert pocet_zamestnancu == 2
    assert pocet_nedostupnosti == 1


def test_souhrn_vstupu_bez_nedostupnosti_vraci_nulu(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))

    pocet_zamestnancu, pocet_nedostupnosti = souhrn_vstupu(conn, 2026, 8)
    assert pocet_zamestnancu == 1
    assert pocet_nedostupnosti == 0


def test_souhrn_vstupu_ignoruje_nedostupnost_mimo_mesic(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 9, 1), date(2026, 9, 5), "DOV")

    _, pocet_nedostupnosti = souhrn_vstupu(conn, 2026, 8)
    assert pocet_nedostupnosti == 0


# --- nastavení (úkol 5: parametry pravidel, profily normalni/krizovy) ---

_NASTAVENI_KRIZOVY = NastaveniProfilu(
    profil="krizovy", denni_min=2, denni_max=3, nocni_min=1, nocni_max=2,
    max_v_rade=3, max_smen_mesic=16,
)


def test_nastaveni_pro_profil_bez_ulozeni_vraci_none(conn):
    assert repo.nastaveni_pro_profil(conn, "normalni") is None


def test_nastaveni_pro_profil_bez_tabulky_vraci_none(conn):
    """Existující data/rozpis.db bez ruční migrace (viz STAV-FAZE3.md)
    tabulku nastaveni vůbec nemá - CLI (na rozdíl od webu) to nesmí
    shodit na syrový OperationalError, jen se chová jako bez uloženého
    profilu (fallback na config.yaml)."""
    conn.execute("DROP TABLE nastaveni")
    assert repo.nastaveni_pro_profil(conn, "normalni") is None


def test_ulozit_a_nacist_nastaveni(conn):
    repo.ulozit_nastaveni(conn, _NASTAVENI_KRIZOVY)

    nacteno = repo.nastaveni_pro_profil(conn, "krizovy")
    assert nacteno == _NASTAVENI_KRIZOVY
    assert repo.nastaveni_pro_profil(conn, "normalni") is None  # profily nezávislé


def test_ulozit_nastaveni_je_upsert(conn):
    repo.ulozit_nastaveni(conn, _NASTAVENI_KRIZOVY)
    zmenene = replace(_NASTAVENI_KRIZOVY, nocni_min=2, max_smen_mesic=18)
    repo.ulozit_nastaveni(conn, zmenene)

    assert repo.nastaveni_pro_profil(conn, "krizovy") == zmenene


def test_config_pro_mesic_bez_db_nastaveni_pouzije_config_yaml(conn):
    for jmeno in ["Alena"] + ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))

    config = config_pro_mesic(conn, 2026, 8)
    assert config.obsazeni.denni_min == 3  # z config.yaml, viz obsazeni.denni_min
    assert config.pravidla.max_smen_mesic == 15


def test_config_pro_mesic_pouzije_db_nastaveni_kdyz_existuje(conn):
    for jmeno in ["Alena"] + ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.ulozit_nastaveni(
        conn,
        NastaveniProfilu(
            profil="normalni", denni_min=2, denni_max=2, nocni_min=1, nocni_max=1,
            max_v_rade=2, max_smen_mesic=10,
        ),
    )

    config = config_pro_mesic(conn, 2026, 8)  # výchozí profil="normalni"
    assert config.obsazeni.denni_min == 2
    assert config.obsazeni.denni_max == 2
    assert config.pravidla.max_smen_mesic == 10


def test_config_pro_mesic_profil_krizovy_nezavisi_na_normalni(conn):
    for jmeno in ["Alena"] + ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.ulozit_nastaveni(conn, _NASTAVENI_KRIZOVY)

    # "normalni" profil nemá v DB řádek -> pořád spadne na config.yaml
    config_normalni = config_pro_mesic(conn, 2026, 8, profil="normalni")
    assert config_normalni.obsazeni.denni_min == 3

    config_krizovy = config_pro_mesic(conn, 2026, 8, profil="krizovy")
    assert config_krizovy.obsazeni.nocni_min == 1
    assert config_krizovy.pravidla.max_smen_mesic == 16


def test_zmena_nastaveni_se_propise_do_generovani(conn):
    """Úkol 5, požadovaný test: "změna parametru se propíše do
    generování" - obsazení nastavené v DB musí ovlivnit skutečně
    vygenerovaný rozpis, ne jen Config objekt."""
    for jmeno in ["Alena"] + ZBYVAJICI_11:
        repo.pridat_zamestnance(conn, jmeno, date(2020, 1, 1))
    repo.ulozit_nastaveni(
        conn,
        NastaveniProfilu(
            profil="normalni", denni_min=2, denni_max=2, nocni_min=1, nocni_max=1,
            max_v_rade=3, max_smen_mesic=15,
        ),
    )

    config = config_pro_mesic(conn, 2026, 8)
    schedule = generate_schedule(config, time_limit_s=10.0)

    for den in range(1, schedule.pocet_dni + 1):
        pocet_d, pocet_n = schedule.obsazeni_dne(den)
        assert pocet_d == 2
        assert pocet_n == 1
