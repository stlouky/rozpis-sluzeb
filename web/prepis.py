"""Sestavení dat pro pohled 'přepis do Cygnusu' (úkol 7).

Přepis do Cygnusu je záměrně ruční (viz CLAUDE.md/NAVRH.md) - appka ho
nenahrazuje, tenhle pohled jen usnadní čtení při ručním přepisování:
seznam po zaměstnancích (abecedně, jako v Cygnusu), u každého
chronologicky JEN dny, kde je co přepisovat (směna nebo nedostupnost se
známým důvodem) - prázdné/volné dny bez důvodu se přeskakují, ať se
vedoucí neprokliká přes prázdno.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from db.bridge import schedule_z_db
from solver.schedule import CZ_DNY

from .mrizka import NAZEV_NEDOSTUPNOSTI

_NAZEV_SMENY = {"D": "Denní", "N": "Noční"}


@dataclass(frozen=True)
class PolozkaPrepisu:
    den: int
    den_tydne: str
    popis: str  # "Denní"/"Noční" nebo plný název nedostupnosti (NAZEV_NEDOSTUPNOSTI)


@dataclass(frozen=True)
class RadekPrepisu:
    jmeno: str
    polozky: list[PolozkaPrepisu]


@dataclass(frozen=True)
class PrepisMesice:
    rok: int
    mesic: int
    radky: list[RadekPrepisu]


def sestavit_prepis(conn: sqlite3.Connection, rok: int, mesic: int) -> PrepisMesice:
    schedule = schedule_z_db(conn, rok, mesic)

    radky = []
    for jmeno in schedule.jmena_serazena:
        polozky = []
        for den in range(1, schedule.pocet_dni + 1):
            smena = schedule.smena_zamestnance(jmeno, den)
            if smena:
                popis = _NAZEV_SMENY[smena]
            else:
                duvod = schedule.duvod_nedostupnosti(jmeno, den)
                if duvod is None:
                    continue  # volno bez důvodu - nic k přepsání
                popis = NAZEV_NEDOSTUPNOSTI.get(duvod, duvod)
            polozky.append(
                PolozkaPrepisu(
                    den=den,
                    den_tydne=CZ_DNY[date(rok, mesic, den).weekday()],
                    popis=popis,
                )
            )
        radky.append(RadekPrepisu(jmeno=jmeno, polozky=polozky))

    return PrepisMesice(rok=rok, mesic=mesic, radky=radky)
