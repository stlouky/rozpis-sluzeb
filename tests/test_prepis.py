"""Testy pohledu 'přepis do Cygnusu' (úkol 7, viz zadani-faze3-web.md)."""

from datetime import date

import pytest

from db import repository as repo
from solver.schedule import Schedule
from web.mrizka import sestavit_mrizku
from web.prepis import sestavit_prepis


@pytest.fixture
def conn():
    connection = repo.pripojit(":memory:")
    repo.inicializovat_schema(connection)
    yield connection
    connection.close()


def test_sestavit_prepis_radky_jsou_abecedne(conn):
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))

    prepis = sestavit_prepis(conn, 2026, 8)
    assert [r.jmeno for r in prepis.radky] == ["Alena", "Bedřich"]


def test_sestavit_prepis_obsahuje_smeny_s_nazvem(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 1): "D", ("Alena", 2): "N"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)

    prepis = sestavit_prepis(conn, 2026, 8)
    polozky = {p.den: p.popis for p in prepis.radky[0].polozky}
    assert polozky[1] == "Denní"
    assert polozky[2] == "Noční"


def test_sestavit_prepis_obsahuje_nedostupnost_s_duvodem(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 5), date(2026, 8, 5), "DOV")

    prepis = sestavit_prepis(conn, 2026, 8)
    polozky = {p.den: p.popis for p in prepis.radky[0].polozky}
    assert polozky[5] == "Dovolená"


def test_sestavit_prepis_preskakuje_volno_bez_duvodu(conn):
    repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    prepis = sestavit_prepis(conn, 2026, 8)
    assert prepis.radky[0].polozky == []


def test_sestavit_prepis_den_tydne_a_razeni(conn):
    id_ = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena",),
        smeny={("Alena", 3): "N"}, status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    repo.pridat_nedostupnost(conn, id_, date(2026, 8, 10), date(2026, 8, 10), "NEM")

    prepis = sestavit_prepis(conn, 2026, 8)
    dny = [p.den for p in prepis.radky[0].polozky]
    assert dny == [3, 10]  # chronologicky
    prvni = prepis.radky[0].polozky[0]
    assert prvni.den_tydne == "Po"  # 3.8.2026 je pondělí


# --- "obsah přepisového pohledu odpovídá mřížce" (úkol 7, zadaný test) ---

def test_sestavit_prepis_odpovida_mrizce(conn):
    id_alena = repo.pridat_zamestnance(conn, "Alena", date(2020, 1, 1))
    repo.pridat_zamestnance(conn, "Bedřich", date(2020, 1, 1))
    schedule = Schedule(
        rok=2026, mesic=8, jmena=("Alena", "Bedřich"),
        smeny={("Alena", 1): "D", ("Bedřich", 2): "N"},
        status="OPTIMAL", cas_reseni=0.1,
    )
    repo.ulozit_rozpis(conn, schedule)
    repo.pridat_nedostupnost(conn, id_alena, date(2026, 8, 5), date(2026, 8, 5), "DOV")

    mrizka = sestavit_mrizku(conn, 2026, 8, je_admin=True)
    prepis = sestavit_prepis(conn, 2026, 8)

    assert [r.jmeno for r in mrizka.radky] == [r.jmeno for r in prepis.radky]

    for radek_mrizky, radek_prepisu in zip(mrizka.radky, prepis.radky):
        polozky_prepisu = {p.den: p.popis for p in radek_prepisu.polozky}
        for den, bunka in zip(mrizka.dny, radek_mrizky.bunky):
            if bunka.smena:
                assert polozky_prepisu[den] in ("Denní", "Noční")
            elif bunka.nedostupnost:
                assert polozky_prepisu[den] == bunka.nazev_nedostupnosti
            else:
                # volno bez důvodu - mřížka i přepis ho mlčky vynechají
                assert den not in polozky_prepisu
