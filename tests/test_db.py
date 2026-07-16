"""Testy datové vrstvy nad SQLite (fáze 2)."""

from datetime import date

import pytest

from db import repository as repo
from db.bridge import config_pro_mesic
from solver.core import generate_schedule

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


def test_deaktivovany_zamestnanec_zmizi_po_datu_odchodu(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.deaktivovat_zamestnance(conn, id_, date(2026, 6, 30))

    aktivni_pred = repo.aktivni_zamestnanci(conn, date(2026, 6, 15))
    assert id_ in {z.id for z in aktivni_pred}

    aktivni_v_den_odchodu = repo.aktivni_zamestnanci(conn, date(2026, 6, 30))
    assert id_ in {z.id for z in aktivni_v_den_odchodu}  # aktivni_do je včetně

    aktivni_po = repo.aktivni_zamestnanci(conn, date(2026, 7, 1))
    assert id_ not in {z.id for z in aktivni_po}

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


def test_zrusit_nedostupnost(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    ned_id = repo.pridat_nedostupnost(conn, id_, date(2026, 8, 3), date(2026, 8, 9), "DOV")
    repo.zrusit_nedostupnost(conn, ned_id)

    assert repo.nedostupnosti_v_obdobi(conn, date(2026, 8, 1), date(2026, 8, 31)) == []


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
