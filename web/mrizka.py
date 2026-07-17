"""Sestavení dat pro mřížku měsíce (úkol 3) - z DB do tvaru pro šablonu.

Obsazení a souhrn per zaměstnanec počítá Schedule (solver/schedule.py,
sestavené přes db.bridge.schedule_z_db) - stejná logika jako u PDF exportu
(vystup/pdf.py), žádná duplicitní implementace.
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date

from db import repository as repo
from db.bridge import dny_v_mesici, schedule_z_db
from solver.schedule import CZ_DNY


# Zkratky pro buňku mřížky - stejné jako v legendě (NEM/OST/POZ). NEM a OST
# jsou už na 3 znacích, jen POZADAVEK je potřeba zkrátit; neznámé/budoucí
# typy se zkrátí obecně na první 3 znaky (viz Bunka.text), ať nový typ
# nedostupnosti mřížku nerozbije, i kdyby se sem zapomnělo doplnit zkratku.
_ZKRATKA_NEDOSTUPNOSTI = {"POZADAVEK": "POZ"}

# Plný název pro title/tooltip buňky (viz web/sablony/mrizka.html) - i
# nahled ho smí vidět, jde jen o rozepsání zkratky/barvy, ne o poznámku.
_NAZEV_NEDOSTUPNOSTI = {
    "DOV": "Dovolená",
    "NEM": "Nemoc",
    "OST": "Ostatní",
    "POZADAVEK": "Požadavek",
}


@dataclass(frozen=True)
class Bunka:
    smena: str | None  # 'D' | 'N' | None
    nedostupnost: str | None  # 'DOV' | 'NEM' | 'OST' | 'POZADAVEK' | None
    poznamka: str | None  # jen pro admina (viz sestavit_mrizku), jinak vždy None

    @property
    def text(self) -> str:
        if self.smena:
            return self.smena
        if self.nedostupnost and self.nedostupnost != "DOV":
            return _ZKRATKA_NEDOSTUPNOSTI.get(self.nedostupnost, self.nedostupnost[:3])
        return ""

    @property
    def nazev_nedostupnosti(self) -> str | None:
        """Plný název typu pro title/tooltip - zkratka v buňce (text výš)
        by sama o sobě nemusela být čitelná."""
        return _NAZEV_NEDOSTUPNOSTI.get(self.nedostupnost) if self.nedostupnost else None

    @property
    def trida(self) -> str:
        """CSS třída podle obsahu buňky - barvy odpovídají vystup/pdf.py
        (viz styl.css), prázdný řetězec = žádná (volný/nevyplněný den)."""
        if self.smena == "D":
            return "smena-d"
        if self.smena == "N":
            return "smena-n"
        if self.nedostupnost == "DOV":
            return "nedostupnost-dov"
        if self.nedostupnost:
            return "nedostupnost-jina"
        return ""


@dataclass(frozen=True)
class RadekZamestnance:
    jmeno: str
    bunky: list[Bunka]
    pocet_d: int
    pocet_n: int
    pocet_vikendu: int


@dataclass(frozen=True)
class MrizkaMesice:
    rok: int
    mesic: int
    dny: list[int]
    dny_tydne: list[str]
    vikendy: list[bool]
    radky: list[RadekZamestnance]
    obsazeni: list[tuple[int, int]]  # (počet D, počet N) za den, stejné pořadí jako dny


def _poznamky_v_mesici(
    conn: sqlite3.Connection, rok: int, mesic: int
) -> dict[tuple[str, int], str]:
    """Poznámka k nedostupnosti po dnech - volá se JEN pro admina (viz
    sestavit_mrizku). Read-only role poznámku nikdy nedostane ani v datech,
    které backend pošle do šablony, ne jen skrytím v HTML (viz CLAUDE.md,
    bezpečnostní invarianty)."""
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])
    jmeno_podle_id = {
        z.id: z.jmeno for z in repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    }

    poznamky: dict[tuple[str, int], str] = {}
    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        if not n.poznamka:
            continue
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue
        for den in dny_v_mesici(n.od, n.do, prvni_den, posledni_den):
            poznamky[(jmeno, den)] = n.poznamka
    return poznamky


def sestavit_mrizku(conn: sqlite3.Connection, rok: int, mesic: int, je_admin: bool) -> MrizkaMesice:
    """Sestaví data mřížky pro daný měsíc. poznamka v jednotlivých Bunka
    je vyplněná JEN když je_admin=True (viz _poznamky_v_mesici)."""
    schedule = schedule_z_db(conn, rok, mesic)
    dny = list(range(1, schedule.pocet_dni + 1))

    poznamky = _poznamky_v_mesici(conn, rok, mesic) if je_admin else {}

    radky = []
    for jmeno in schedule.jmena_serazena:
        bunky = []
        for den in dny:
            smena = schedule.smena_zamestnance(jmeno, den)
            nedostupnost = None if smena else schedule.duvod_nedostupnosti(jmeno, den)
            bunky.append(
                Bunka(
                    smena=smena,
                    nedostupnost=nedostupnost,
                    poznamka=poznamky.get((jmeno, den)),
                )
            )
        souhrn = schedule.souhrn_zamestnance(jmeno)
        radky.append(
            RadekZamestnance(
                jmeno=jmeno,
                bunky=bunky,
                pocet_d=souhrn["smeny"] - souhrn["nocni"],
                pocet_n=souhrn["nocni"],
                pocet_vikendu=souhrn["vikendy"],
            )
        )

    return MrizkaMesice(
        rok=rok,
        mesic=mesic,
        dny=dny,
        dny_tydne=[CZ_DNY[date(rok, mesic, d).weekday()] for d in dny],
        vikendy=[schedule.je_vikend(d) for d in dny],
        radky=radky,
        obsazeni=[schedule.obsazeni_dne(d) for d in dny],
    )
