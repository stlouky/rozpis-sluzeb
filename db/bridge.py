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

from . import repository as repo

DEFAULT_CONFIG_YAML = Path(__file__).resolve().parent.parent / "config.yaml"


def _dny_v_mesici(od: date, do: date, prvni_den: date, posledni_den: date) -> list[int]:
    """Ořízne interval [od, do] na rozsah měsíce [prvni_den, posledni_den]
    a vrátí seznam dní v měsíci (1-indexováno).
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

    nedostupnosti: dict[str, set[int]] = {}
    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue  # zaměstnanec v tomto měsíci není aktivní
        dny = _dny_v_mesici(n.od, n.do, prvni_den, posledni_den)
        nedostupnosti.setdefault(jmeno, set()).update(dny)

    nekompatibilni_dvojice = [
        [jmeno_podle_id[d.zamestnanec_a_id], jmeno_podle_id[d.zamestnanec_b_id]]
        for d in repo.dvojice_vsechny(conn)
        if d.zamestnanec_a_id in jmeno_podle_id and d.zamestnanec_b_id in jmeno_podle_id
    ]

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
        "vahy": vahy_config.get("vahy", {}),
    }
    return config_from_dict(data)
