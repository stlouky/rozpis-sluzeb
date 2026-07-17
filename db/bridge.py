"""Most mezi DB a solverem: config_pro_mesic(conn, rok, mesic) -> Config.

Zaměstnanci, jejich nedostupnosti a nekompatibilní dvojice se berou ze
stavu DB. Obsazení, pravidla a váhy zatím zůstávají v config.yaml (fáze 2
je jen datová vrstva - správa vah/obsazení přes DB je otázka pro pozdější
fázi, až bude UI).
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import yaml

from solver.config import Config, config_from_dict
from solver.schedule import Schedule

from . import repository as repo

DEFAULT_CONFIG_YAML = Path(__file__).resolve().parent.parent / "config.yaml"


def dny_v_mesici(od: date, do: date, prvni_den: date, posledni_den: date) -> list[int]:
    """Ořízne interval [od, do] na rozsah měsíce [prvni_den, posledni_den]
    a vrátí seznam dní v měsíci (1-indexováno). Veřejné - sdílené i s
    web/mrizka.py (poznámky k nedostupnostem), ne jen s config_pro_mesic.
    """
    zacatek = max(od, prvni_den)
    konec = min(do, posledni_den)
    dny = []
    d = zacatek
    while d <= konec:
        dny.append(d.day)
        d += timedelta(days=1)
    return dny


def config_pro_mesic(
    conn: sqlite3.Connection,
    rok: int,
    mesic: int,
    config_yaml_cesta: str | Path = DEFAULT_CONFIG_YAML,
) -> Config:
    """Sestaví Config pro daný měsíc ze stavu DB + obsazení/pravidla/váhy
    z config_yaml_cesta.
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])

    aktivni = repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    jmeno_podle_id = {z.id: z.jmeno for z in aktivni}

    zamestnanci_data = [
        {"jmeno": z.jmeno, "stitky": z.seznam_stitku} for z in aktivni
    ]
    max_smen_mesic_override = {
        z.jmeno: z.max_smen_mesic for z in aktivni if z.max_smen_mesic is not None
    }
    max_v_rade_override = {
        z.jmeno: z.max_za_sebou for z in aktivni if z.max_za_sebou is not None
    }

    nedostupnosti: dict[str, set[int]] = {}
    duvody_nedostupnosti: dict[str, dict[int, str]] = {}
    zakazane_smeny: dict[str, dict[int, tuple[str, ...]]] = {}

    # Trvalé osobní omezení typu směny (zamestnanec.zakaz_smeny) - na
    # rozdíl od nedostupnost.zakazana_smena (časově ohraničené) platí pro
    # VŠECHNY dny měsíce, proto se rovnou promítne do stejné zakazane_smeny
    # struktury, kterou solver už umí (žádná nová solver logika navíc).
    for z in aktivni:
        if z.zakaz_smeny is not None:
            dny_omezeni = zakazane_smeny.setdefault(z.jmeno, {})
            for den in range(1, posledni_den.day + 1):
                dny_omezeni[den] = dny_omezeni.get(den, ()) + (z.zakaz_smeny,)

    # Nástup/odchod uprostřed měsíce: aktivni_zamestnanci_v_obdobi vrátí
    # zaměstnance, jehož aktivní interval se s měsícem JEN překrývá (viz
    # repository.py) - bez tohohle by zůstal solveru "dostupný" i po dnech,
    # kdy už fakticky není v pracovním poměru.
    vsechny_dny_mesice = set(range(1, posledni_den.day + 1))
    for z in aktivni:
        aktivni_dny = set(
            dny_v_mesici(z.aktivni_od, z.aktivni_do or posledni_den, prvni_den, posledni_den)
        )
        mimo_pomer = vsechny_dny_mesice - aktivni_dny
        if mimo_pomer:
            nedostupnosti.setdefault(z.jmeno, set()).update(mimo_pomer)
            duvody = duvody_nedostupnosti.setdefault(z.jmeno, {})
            for den in mimo_pomer:
                duvody[den] = "MIMO_POMER"

    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue  # zaměstnanec v tomto měsíci není aktivní
        dny = dny_v_mesici(n.od, n.do, prvni_den, posledni_den)
        if n.zakazana_smena is None:
            nedostupnosti.setdefault(jmeno, set()).update(dny)
            duvody = duvody_nedostupnosti.setdefault(jmeno, {})
            for den in dny:
                duvody[den] = n.typ
        else:
            dny_omezeni = zakazane_smeny.setdefault(jmeno, {})
            for den in dny:
                dny_omezeni[den] = dny_omezeni.get(den, ()) + (n.zakazana_smena,)

    nekompatibilni_dvojice = []
    zakazane_dvojice = []
    for d in repo.dvojice_vsechny(conn):
        if d.zamestnanec_a_id not in jmeno_podle_id or d.zamestnanec_b_id not in jmeno_podle_id:
            continue
        par = [jmeno_podle_id[d.zamestnanec_a_id], jmeno_podle_id[d.zamestnanec_b_id]]
        if d.typ == "zakazano":
            zakazane_dvojice.append(par)
        else:
            nekompatibilni_dvojice.append(par)

    with open(config_yaml_cesta, encoding="utf-8") as f:
        vahy_config = yaml.safe_load(f)

    data = {
        "rok": rok,
        "mesic": mesic,
        "zamestnanci": zamestnanci_data,
        "obsazeni": vahy_config["obsazeni"],
        "pravidla": vahy_config["pravidla"],
        "nedostupnosti": {jmeno: sorted(dny) for jmeno, dny in nedostupnosti.items()},
        "nekompatibilni_dvojice": nekompatibilni_dvojice,
        "zakazane_dvojice": zakazane_dvojice,
        "vahy": vahy_config.get("vahy", {}),
        "duvody_nedostupnosti": duvody_nedostupnosti,
        "zakazane_smeny": zakazane_smeny,
        "max_smen_mesic_override": max_smen_mesic_override,
        "max_v_rade_override": max_v_rade_override,
    }
    return config_from_dict(data)


def souhrn_vstupu(conn: sqlite3.Connection, rok: int, mesic: int) -> tuple[int, int]:
    """(počet aktivních zaměstnanců, počet nedostupností) pro daný měsíc -
    rychlý přehled vstupu PŘED spuštěním solveru (viz db/cli.py generuj).

    config_pro_mesic ani generate_schedule nijak nekontrolují, jestli je
    vstup podezřele řídký - prázdná nedostupnost je pro solver validní
    stav (nikdo nemá nic nahlášeno), ne chyba, takže bez tohohle souhrnu
    není vidět, když někdo zapomene import-txt/zadání nedostupností
    spustit před generováním (viz incident: rozpis vznikl s nereálně
    volnou rukou, protože tabulka nedostupnost byla prázdná).
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])
    pocet_zamestnancu = len(repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den))
    pocet_nedostupnosti = len(repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den))
    return pocet_zamestnancu, pocet_nedostupnosti


def schedule_z_db(conn: sqlite3.Connection, rok: int, mesic: int) -> Schedule:
    """Sestaví Schedule (solver/schedule.py) z uložených směn v DB - pro
    zobrazení (web mřížka úkol 3, přepis do Cygnusu úkol 7), ať se
    obsazení/souhrn počítá stejnou logikou jako u PDF exportu
    (vystup/pdf.py), ne duplicitně.

    Na rozdíl od config_pro_mesic (DB -> vstup solveru) je tohle DB ->
    výstupní tvar solveru, čistě pro čtení uložených dat.
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])

    aktivni = repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    jmeno_podle_id = {z.id: z.jmeno for z in aktivni}
    jmena = tuple(jmeno_podle_id.values())

    smeny: dict[tuple[str, int], str] = {}
    for s in repo.smeny_v_mesici(conn, rok, mesic):
        jmeno = jmeno_podle_id.get(s.zamestnanec_id)
        if jmeno is None:
            continue  # zaměstnanec mimo aktivní rozsah měsíce (viz níž)
        smeny[(jmeno, s.datum.day)] = s.typ

    duvody_nedostupnosti: dict[tuple[str, int], str] = {}
    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue
        for den in dny_v_mesici(n.od, n.do, prvni_den, posledni_den):
            duvody_nedostupnosti.setdefault((jmeno, den), n.typ)

    return Schedule(
        rok=rok,
        mesic=mesic,
        jmena=jmena,
        smeny=smeny,
        status="ULOZENO",
        cas_reseni=0.0,
        duvody_nedostupnosti=duvody_nedostupnosti,
    )
