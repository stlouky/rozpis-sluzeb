"""Sestavení dat pro mřížku měsíce (úkol 3) - z DB do tvaru pro šablonu.

Obsazení a souhrn per zaměstnanec počítá Schedule (solver/schedule.py,
sestavené přes db.bridge.schedule_z_db) - stejná logika jako u PDF exportu
(vystup/pdf.py), žádná duplicitní implementace.
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from db import repository as repo
from db.bridge import config_pro_mesic, dny_v_mesici, schedule_z_db
from solver.schedule import CZ_DNY
from solver.validace import validovat_rozpis


# Zkratky pro buňku mřížky - malými písmeny (ost/poz), ať jsou v buňce
# čitelné, ale opticky nekřičí přes D/N směny, které zůstávají velkými
# (zavedená konvence, viz CLAUDE.md). DOV a NEM v buňce žádný text
# nemají (na přání) - stačí barva, viz Bunka.text/trida. Neznámé/budoucí
# typy se zkrátí obecně na první 3 znaky malými, ať nový typ nedostupnosti
# mřížku nerozbije, i kdyby se sem zapomnělo doplnit zkratku.
_ZKRATKA_NEDOSTUPNOSTI = {"OST": "ost", "SVZ": "svz", "POZADAVEK": "poz"}

# Typy nedostupnosti bez textu v buňce - jen barva (viz Bunka.text).
_BEZ_TEXTU_V_BUNCE = {"DOV", "NEM"}

# Typy, které klikací cyklus buňky umí nastavit (úkol 9) - zbylé typy
# (SVZ, POZADAVEK) i vícedenní záznamy libovolného typu se zadávají jen
# přes /admin/nedostupnosti, ne klikem v mřížce (viz sestavit_mrizku).
TYPY_NEDOSTUPNOSTI_V_CYKLU = ("DOV", "OST", "NEM")

# Plný název pro title/tooltip buňky (viz web/sablony/mrizka.html) - i
# nahled ho smí vidět, jde jen o rozepsání zkratky/barvy, ne o poznámku.
# Veřejné (bez podtržítka) - sdílené i s formulářem nedostupností
# (web/app.py, úkol 5), ať typ->název není na dvou místech.
NAZEV_NEDOSTUPNOSTI = {
    "DOV": "Dovolená",
    "NEM": "Nemoc",
    "OST": "Ostatní",
    "SVZ": "Školení v zařízení",
    "POZADAVEK": "Požadavek",
}


@dataclass(frozen=True)
class Bunka:
    smena: str | None  # 'D' | 'N' | None
    nedostupnost: str | None  # 'DOV' | 'NEM' | 'OST' | 'POZADAVEK' | None
    poznamka: str | None  # jen pro admina (viz sestavit_mrizku), jinak vždy None
    zamcena: bool = False  # úkol 8 - jen nezamčené buňky smí admin klikem upravit
    # Zda cyklus D/N/volno/DOV/OST/NEM (úkol 9) smí na tuhle buňku sáhnout -
    # False i pro nezamčenou buňku, když je den součástí VÍCEdenní
    # nedostupnosti nebo typu mimo D/N/DOV/OST/NEM (viz sestavit_mrizku) -
    # klik by takový záznam mohl nechtěně zkrátit/smazat.
    editovatelna: bool = False
    # Text porušení tvrdého pravidla (nebo více spojených), None = bez
    # porušení - viz solver/validace.py. Zobrazuje se i nahled roli (jde
    # jen o to, že rozpis neodpovídá pravidlům, ne o poznámku).
    duvod_poruseni: str | None = None

    @property
    def text(self) -> str:
        if self.smena:
            return self.smena
        if self.nedostupnost and self.nedostupnost not in _BEZ_TEXTU_V_BUNCE:
            return _ZKRATKA_NEDOSTUPNOSTI.get(self.nedostupnost, self.nedostupnost[:3].lower())
        return ""

    @property
    def nazev_nedostupnosti(self) -> str | None:
        """Plný název typu pro title/tooltip - zkratka v buňce (text výš)
        by sama o sobě nemusela být čitelná."""
        return NAZEV_NEDOSTUPNOSTI.get(self.nedostupnost) if self.nedostupnost else None

    @property
    def nadpis(self) -> str | None:
        """Text pro title/tooltip buňky (úkol 8) - porušení tvrdého
        pravidla (pokud je) + poznámka/název nedostupnosti, spojené
        středníkem. duvod_poruseni a nedostupnost se v praxi nepřekrývají
        (validátor kontroluje jen dny se směnou, viz solver/validace.py),
        ale poznamka může nastat společně s duvod_poruseni (např. ručně
        přiřazená směna v den nahlášené nedostupnosti)."""
        casti = []
        if self.duvod_poruseni:
            casti.append(self.duvod_poruseni)
        if self.poznamka:
            casti.append(self.poznamka)
        elif self.nazev_nedostupnosti:
            casti.append(self.nazev_nedostupnosti)
        return "; ".join(casti) if casti else None

    @property
    def trida(self) -> str:
        """CSS třída podle obsahu buňky - barvy odpovídají vystup/pdf.py
        (viz styl.css), prázdný řetězec = žádná (volný/nevyplněný den).
        NEM má vlastní pastelovou barvu (na přání, pro názornost - snáz
        se v mřížce najde, kdo je nemocný), OST/POZADAVEK sdílí neutrální
        šedou."""
        if self.smena == "D":
            return "smena-d"
        if self.smena == "N":
            return "smena-n"
        if self.nedostupnost == "DOV":
            return "nedostupnost-dov"
        if self.nedostupnost == "NEM":
            return "nedostupnost-nem"
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
    zamestnanec_id: int | None = None  # None jen teoreticky (viz sestavit_mrizku)
    # Porušení tvrdých pravidel nevázaná na konkrétní den (úkol 8: fond
    # přes limit) - zobrazí se u jména, ne v konkrétní buňce.
    varovani: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MrizkaMesice:
    rok: int
    mesic: int
    dny: list[int]
    dny_tydne: list[str]
    vikendy: list[bool]
    radky: list[RadekZamestnance]
    obsazeni: list[tuple[int, int]]  # (počet D, počet N) za den, stejné pořadí jako dny
    # Den je "krizový", když jeho denní NEBO noční obsazení nedosáhne maxima,
    # kterého se v tomhle měsíci jinak běžně dosahuje (viz sestavit_mrizku) -
    # datově řízené, ne natvrdo porovnané s config.yaml, ať to funguje i s
    # jiným profilem obsazení (úkol 5). Noční se počítá zvlášť od denního -
    # podstav v noci (typicky pád na 1 místo 2) je bezpečnostně kritičtější
    # než podstav ve dne, ale den s plným denním obsazením by ho jinak
    # přebil a schoval (viz audit).
    krizove_dny: list[bool]
    # Den porušuje tvrdé pravidlo obsazení (úkol 8: mimo min/max, na
    # rozdíl od krizove_dny výš, které je jen relativní k tomuto měsíci).
    dny_s_porusenim: list[bool]


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

    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, schedule.pocet_dni)
    aktivni = repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    zamestnanec_id_podle_jmena = {z.jmeno: z.id for z in aktivni}
    jmeno_podle_id = {z.id: z.jmeno for z in aktivni}

    # Dny, kam klikací cyklus (úkol 9) NESMÍ sáhnout, i když nejsou
    # zamčené - VÍCEdenní nedostupnost nebo typ mimo TYPY_NEDOSTUPNOSTI_V_CYKLU
    # (SVZ/POZADAVEK) se zadává jen přes /admin/nedostupnosti, ať klik
    # omylem nezkrátí/nesmaže záznam, co se táhne přes víc dní.
    needitovatelne_nedostupnosti: set[tuple[str, int]] = set()
    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue
        if n.od == n.do and n.typ in TYPY_NEDOSTUPNOSTI_V_CYKLU:
            continue  # jednodenní a editovatelného typu - buňka zůstává klikatelná
        for den in dny_v_mesici(n.od, n.do, prvni_den, posledni_den):
            needitovatelne_nedostupnosti.add((jmeno, den))

    # Porušení tvrdých pravidel (úkol 8) - vždy dopočítané, ne jen po
    # ruční úpravě, ať se ukážou i staré/zamčené kolize z generování.
    # Profil "normalni" je stejný výchozí, jaký bere config_pro_mesic i
    # POST /rozpis/generovat bez výslovné volby (viz web/app.py).
    config = config_pro_mesic(conn, rok, mesic)
    poruseni_bunky: dict[tuple[str, int], list[str]] = {}
    poruseni_dne: set[int] = set()
    poruseni_zamestnance: dict[str, list[str]] = {}
    for p in validovat_rozpis(schedule, config):
        if p.zamestnanec is None:
            poruseni_dne.add(p.den)
        elif p.den == 0:
            poruseni_zamestnance.setdefault(p.zamestnanec, []).append(p.popis)
        else:
            poruseni_bunky.setdefault((p.zamestnanec, p.den), []).append(p.popis)

    radky = []
    for jmeno in schedule.jmena_serazena:
        bunky = []
        for den in dny:
            smena = schedule.smena_zamestnance(jmeno, den)
            nedostupnost = None if smena else schedule.duvod_nedostupnosti(jmeno, den)
            duvody = poruseni_bunky.get((jmeno, den))
            zamcena = schedule.je_zamcena(jmeno, den)
            bunky.append(
                Bunka(
                    smena=smena,
                    nedostupnost=nedostupnost,
                    poznamka=poznamky.get((jmeno, den)),
                    zamcena=zamcena,
                    duvod_poruseni="; ".join(duvody) if duvody else None,
                    editovatelna=not zamcena and (jmeno, den) not in needitovatelne_nedostupnosti,
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
                zamestnanec_id=zamestnanec_id_podle_jmena.get(jmeno),
                varovani=poruseni_zamestnance.get(jmeno, []),
            )
        )

    obsazeni = [schedule.obsazeni_dne(d) for d in dny]
    # "Krizový" den = denní NEBO noční obsazení pod maximem, kterého tenhle
    # měsíc jinde běžně dosahuje (ne natvrdo 4/2 - obsazeni_dne může mít i
    # jiný profil, viz úkol 5). Denní a noční se posuzují nezávisle - den
    # s plným denním obsazením, ale podstavenou nocí, musí zůstat krizový
    # (viz audit: noční podstav se dřív schoval za plný denní stav).
    # Bez dat (nikdo nikde plný) se nic neoznačí.
    nejvyssi_denni = max((d for d, _ in obsazeni), default=0)
    nejvyssi_nocni = max((n for _, n in obsazeni), default=0)
    krizove_dny = [
        d < nejvyssi_denni or n < nejvyssi_nocni for d, n in obsazeni
    ]

    return MrizkaMesice(
        rok=rok,
        mesic=mesic,
        dny=dny,
        dny_tydne=[CZ_DNY[date(rok, mesic, d).weekday()] for d in dny],
        vikendy=[schedule.je_vikend(d) for d in dny],
        radky=radky,
        obsazeni=obsazeni,
        krizove_dny=krizove_dny,
        dny_s_porusenim=[d in poruseni_dne for d in dny],
    )


# --- kalendářové widgety požadavků (úkol 9d) ---


@dataclass(frozen=True)
class PolozkaPozadavku:
    id: int
    zamestnanec_id: int
    jmeno: str
    typ_nazev: str
    stav: str  # 'podano' | 'schvaleno' | 'zamitnuto'


@dataclass(frozen=True)
class DenPozadavku:
    den: int
    polozky: list[PolozkaPozadavku]
    # Aktivní zaměstnanci bez celodenní nedostupnosti, počítáno včetně
    # čekajících (jako kdyby se všechno schválilo) - orientační, ne
    # záruka (viz db.bridge.schvalit_nekonfliktni, stejná heuristika).
    volnych_pri_schvaleni: int
    minimum: int  # denni_min + nocni_min aktivního profilu
    riziko: bool  # volnych_pri_schvaleni < minimum


def sestavit_pozadavky_widget(
    conn: sqlite3.Connection, rok: int, mesic: int, profil: str = "normalni"
) -> list[DenPozadavku]:
    """Data pro widgety "Podat požadavek" a "Správa požadavků" (úkol 9d)
    - obsazenost dne napříč VŠEMI typy a stavy nedostupnosti (ne jen
    self-service), ať je vidět, než si někdo přidá vlastní požadavek na
    už nabitý den. Nejnovější položky v rámci dne nahoře (podle id)."""
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])
    pocet_dni = posledni_den.day

    aktivni = repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    jmeno_podle_id = {z.id: z.jmeno for z in aktivni}
    celkem_aktivnich = len(aktivni)

    nastaveni = repo.nastaveni_pro_profil(conn, profil)
    minimum = (nastaveni.denni_min + nastaveni.nocni_min) if nastaveni else 0

    polozky_podle_dne: dict[int, list[PolozkaPozadavku]] = {d: [] for d in range(1, pocet_dni + 1)}
    blokovanych_podle_dne: dict[int, set[int]] = {d: set() for d in range(1, pocet_dni + 1)}

    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue
        for den in dny_v_mesici(n.od, n.do, prvni_den, posledni_den):
            polozky_podle_dne[den].append(
                PolozkaPozadavku(
                    id=n.id,
                    zamestnanec_id=n.zamestnanec_id,
                    jmeno=jmeno,
                    typ_nazev=NAZEV_NEDOSTUPNOSTI.get(n.typ, n.typ),
                    stav=n.stav,
                )
            )
            # celodenní (ne jen "zákaz nočních" apod.) a ne zamítnuté -
            # 'schvaleno' i 'podano' počítáme společně, ať widget ukazuje
            # dostupnost "jako kdyby se schválilo úplně všechno".
            if n.zakazana_smena is None and n.stav != "zamitnuto":
                blokovanych_podle_dne[den].add(n.zamestnanec_id)

    dny_widgetu = []
    for den in range(1, pocet_dni + 1):
        volnych = celkem_aktivnich - len(blokovanych_podle_dne[den])
        dny_widgetu.append(
            DenPozadavku(
                den=den,
                polozky=sorted(polozky_podle_dne[den], key=lambda p: p.id, reverse=True),
                volnych_pri_schvaleni=volnych,
                minimum=minimum,
                riziko=volnych < minimum,
            )
        )
    return dny_widgetu
