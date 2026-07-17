"""Diff mezi uloženým a nově navrženým rozpisem (úkol 9).

"Diff před uložením: kdo / den / bylo -> bude; potvrdit / zahodit" -
POST /rozpis/generovat NEUKLÁDÁ hned výsledek solveru, jen ho porovná
s aktuálním stavem DB a vrátí seznam rozdílů. Zamčené dny se z principu
nikdy nezmění (viz Config.pevne_smeny, solver/core.py), takže se v diffu
nikdy neobjeví - diff tak vždycky ukazuje jen to, co se skutečně mění.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from solver.schedule import CZ_DNY, Schedule

_NAZEV_SMENY = {"D": "Denní", "N": "Noční"}


def _popis_smeny(typ: str | None) -> str:
    return _NAZEV_SMENY.get(typ, "volno")


@dataclass(frozen=True)
class RadekDiffu:
    jmeno: str
    den: int
    den_tydne: str
    bylo: str
    bude: str


def sestavit_diff(puvodni: Schedule, novy: Schedule) -> list[RadekDiffu]:
    """Porovná dva Schedule objekty stejného měsíce, vrátí jen dny, kde
    se hodnota liší (chronologicky, po zaměstnancích v abecedním pořadí
    z `novy` - config_pro_mesic i schedule_z_db berou stejnou množinu
    aktivních zaměstnanců pro daný měsíc, takže se v praxi shoduje)."""
    pocet_dni = calendar.monthrange(novy.rok, novy.mesic)[1]

    radky = []
    for jmeno in novy.jmena_serazena:
        for den in range(1, pocet_dni + 1):
            bylo = puvodni.smena_zamestnance(jmeno, den)
            bude = novy.smena_zamestnance(jmeno, den)
            if bylo == bude:
                continue
            radky.append(
                RadekDiffu(
                    jmeno=jmeno,
                    den=den,
                    den_tydne=CZ_DNY[date(novy.rok, novy.mesic, den).weekday()],
                    bylo=_popis_smeny(bylo),
                    bude=_popis_smeny(bude),
                )
            )
    return radky
