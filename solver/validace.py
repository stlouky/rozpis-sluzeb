"""Validace hotového rozpisu proti tvrdým pravidlům (úkol 8).

Na rozdíl od solver/core.py (HLEDÁ řešení, které pravidla splňuje), tenhle
modul KONTROLUJE hotový rozpis (typicky po ruční úpravě buňky v mřížce) -
jen řekne, co je porušené. Nic neopravuje a nic neblokuje - admin smí
vědomě uložit i porušený stav (realita > solver, viz zadani-faze3-web.md
úkol 8: "admin smí vědomě uložit, porušené buňky označené").
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .schedule import Schedule


@dataclass(frozen=True)
class Poruseni:
    """Jedno porušení tvrdého pravidla. zamestnanec=None = plošné
    porušení vázané na den jako celek (obsazení), ne na konkrétní osobu."""

    zamestnanec: str | None
    den: int
    popis: str


def validovat_rozpis(schedule: Schedule, config: Config) -> list[Poruseni]:
    """Vrátí seznam všech porušení tvrdých pravidel z CLAUDE.md v daném
    rozpisu. Prázdný seznam = rozpis je v pořádku."""
    poruseni: list[Poruseni] = []
    dny = range(1, schedule.pocet_dni + 1)
    o = config.obsazeni

    for den in dny:
        pocet_d, pocet_n = schedule.obsazeni_dne(den)
        if pocet_d < o.denni_min:
            poruseni.append(Poruseni(None, den, f"denní obsazení {pocet_d} pod minimem {o.denni_min}"))
        elif pocet_d > o.denni_max:
            poruseni.append(Poruseni(None, den, f"denní obsazení {pocet_d} nad maximem {o.denni_max}"))
        if pocet_n < o.nocni_min:
            poruseni.append(Poruseni(None, den, f"noční obsazení {pocet_n} pod minimem {o.nocni_min}"))
        elif pocet_n > o.nocni_max:
            poruseni.append(Poruseni(None, den, f"noční obsazení {pocet_n} nad maximem {o.nocni_max}"))

    for a, b in config.zakazane_dvojice:
        for den in dny:
            smena_a = schedule.smena_zamestnance(a, den)
            smena_b = schedule.smena_zamestnance(b, den)
            if smena_a is not None and smena_a == smena_b:
                poruseni.append(Poruseni(a, den, f"zakázaná dvojice s {b} ({smena_a})"))
                poruseni.append(Poruseni(b, den, f"zakázaná dvojice s {a} ({smena_a})"))

    for jmeno in schedule.jmena:
        max_v_rade = config.max_v_rade_override.get(jmeno, config.pravidla.max_v_rade)
        strop = config.max_smen_mesic_override.get(jmeno, config.pravidla.max_smen_mesic)
        nedostupny = set(config.nedostupnosti.get(jmeno, ()))
        zakazane_dny = config.zakazane_smeny.get(jmeno, {})

        v_rade = 0
        nocni_v_rade = 0
        pocet_smen = 0
        for den in dny:
            smena = schedule.smena_zamestnance(jmeno, den)

            if smena is None:
                v_rade = 0
                nocni_v_rade = 0
                continue

            pocet_smen += 1

            # N -> D zakázáno
            if den > 1 and schedule.smena_zamestnance(jmeno, den - 1) == "N" and smena == "D":
                poruseni.append(Poruseni(jmeno, den, "denní směna hned po noční"))

            # po 2 nočních v řadě povinně 2 dny volna (CLAUDE.md) - core.py
            # tohle při generování vynucuje jako tvrdé pravidlo (dve_nocni),
            # ale validovat_rozpis to samo nekontrolovalo (nález auditu
            # appky): ruční úprava buňky mohla uložit N,N,volno,D bez
            # jakéhokoli hlášeného porušení.
            if smena == "N" and den > 1 and schedule.smena_zamestnance(jmeno, den - 1) == "N":
                for offset in (1, 2):
                    den_po = den + offset
                    if den_po <= schedule.pocet_dni and schedule.smena_zamestnance(jmeno, den_po) is not None:
                        poruseni.append(
                            Poruseni(jmeno, den_po, "chybí den volna po 2 nočních v řadě")
                        )

            # nedostupnost (celý den, nebo jen tenhle typ směny)
            if den in nedostupny:
                poruseni.append(Poruseni(jmeno, den, "směna v den nahlášené nedostupnosti"))
            elif smena in zakazane_dny.get(den, ()):
                poruseni.append(Poruseni(jmeno, den, f"zakázaný typ směny ({smena}) tento den"))

            v_rade += 1
            if v_rade > max_v_rade:
                poruseni.append(Poruseni(jmeno, den, f"více než {max_v_rade} směn v řadě"))

            if smena == "N":
                nocni_v_rade += 1
                if nocni_v_rade > 2:
                    poruseni.append(Poruseni(jmeno, den, "více než 2 noční směny v řadě"))
            else:
                nocni_v_rade = 0

        if pocet_smen > strop:
            poruseni.append(
                Poruseni(jmeno, 0, f"{pocet_smen} směn v měsíci překračuje strop {strop}")
            )

    return poruseni
