"""Repository nad SQLite - čisté sqlite3, žádný ORM.

Zaměstnanci se nikdy nemažou (viz CLAUDE.md/NAVRH.md) - odchod se řeší
nastavením aktivni_do, historie rozpisů tak zůstává konzistentní.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .models import Dvojice, Nedostupnost, Zamestnanec

SCHEMA_CESTA = Path(__file__).resolve().parent / "schema.sql"


def pripojit(cesta: str | Path) -> sqlite3.Connection:
    """Otevře připojení k SQLite souboru (nebo ':memory:'). Neinicializuje
    schéma - k tomu slouží inicializovat_schema().
    """
    conn = sqlite3.connect(cesta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def inicializovat_schema(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_CESTA, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def _na_datum(hodnota: str | None) -> date | None:
    return date.fromisoformat(hodnota) if hodnota else None


def _zamestnanec_z_radku(radek: sqlite3.Row) -> Zamestnanec:
    return Zamestnanec(
        id=radek["id"],
        jmeno=radek["jmeno"],
        aktivni_od=_na_datum(radek["aktivni_od"]),
        aktivni_do=_na_datum(radek["aktivni_do"]),
        stitky=radek["stitky"],
    )


def _nedostupnost_z_radku(radek: sqlite3.Row) -> Nedostupnost:
    return Nedostupnost(
        id=radek["id"],
        zamestnanec_id=radek["zamestnanec_id"],
        od=_na_datum(radek["od"]),
        do=_na_datum(radek["do"]),
        typ=radek["typ"],
        poznamka=radek["poznamka"],
    )


def _dvojice_z_radku(radek: sqlite3.Row) -> Dvojice:
    return Dvojice(
        id=radek["id"],
        zamestnanec_a_id=radek["zamestnanec_a_id"],
        zamestnanec_b_id=radek["zamestnanec_b_id"],
        typ=radek["typ"],
    )


# --- zaměstnanci ---

def pridat_zamestnance(
    conn: sqlite3.Connection,
    jmeno: str,
    aktivni_od: date,
    stitky: list[str] | None = None,
) -> int:
    kurzor = conn.execute(
        "INSERT INTO zamestnanec (jmeno, aktivni_od, stitky) VALUES (?, ?, ?)",
        (jmeno, aktivni_od.isoformat(), ",".join(stitky or [])),
    )
    conn.commit()
    return kurzor.lastrowid


def deaktivovat_zamestnance(conn: sqlite3.Connection, zamestnanec_id: int, aktivni_do: date) -> None:
    """Nastaví datum odchodu. Zaměstnanec se nikdy nemaže."""
    conn.execute(
        "UPDATE zamestnanec SET aktivni_do = ? WHERE id = ?",
        (aktivni_do.isoformat(), zamestnanec_id),
    )
    conn.commit()


def opravit_jmeno_zamestnance(conn: sqlite3.Connection, zamestnanec_id: int, jmeno: str) -> None:
    """Opraví jméno (typo/nesprávný zápis) - na rozdíl od deaktivace nejde
    o fluktuaci, jen o opravu chybného záznamu."""
    conn.execute(
        "UPDATE zamestnanec SET jmeno = ? WHERE id = ?",
        (jmeno, zamestnanec_id),
    )
    conn.commit()


def aktivni_zamestnanci(conn: sqlite3.Connection, datum: date) -> list[Zamestnanec]:
    """Zaměstnanci aktivní k jednomu konkrétnímu datu."""
    return aktivni_zamestnanci_v_obdobi(conn, datum, datum)


def aktivni_zamestnanci_v_obdobi(conn: sqlite3.Connection, od: date, do: date) -> list[Zamestnanec]:
    """Zaměstnanci, jejichž aktivní interval se překrývá s [od, do]."""
    radky = conn.execute(
        """
        SELECT * FROM zamestnanec
        WHERE aktivni_od <= ?
          AND (aktivni_do IS NULL OR aktivni_do >= ?)
        ORDER BY id
        """,
        (do.isoformat(), od.isoformat()),
    ).fetchall()
    return [_zamestnanec_z_radku(r) for r in radky]


# --- nedostupnosti ---

def pridat_nedostupnost(
    conn: sqlite3.Connection,
    zamestnanec_id: int,
    od: date,
    do: date,
    typ: str,
    poznamka: str | None = None,
) -> int:
    kurzor = conn.execute(
        "INSERT INTO nedostupnost (zamestnanec_id, od, do, typ, poznamka) VALUES (?, ?, ?, ?, ?)",
        (zamestnanec_id, od.isoformat(), do.isoformat(), typ, poznamka),
    )
    conn.commit()
    return kurzor.lastrowid


def zrusit_nedostupnost(conn: sqlite3.Connection, nedostupnost_id: int) -> None:
    conn.execute("DELETE FROM nedostupnost WHERE id = ?", (nedostupnost_id,))
    conn.commit()


def nedostupnosti_v_obdobi(conn: sqlite3.Connection, od: date, do: date) -> list[Nedostupnost]:
    """Nedostupnosti, jejichž interval se překrývá s [od, do]."""
    radky = conn.execute(
        """
        SELECT * FROM nedostupnost
        WHERE od <= ? AND do >= ?
        ORDER BY id
        """,
        (do.isoformat(), od.isoformat()),
    ).fetchall()
    return [_nedostupnost_z_radku(r) for r in radky]


# --- dvojice ---

def pridat_dvojici(
    conn: sqlite3.Connection,
    zamestnanec_a_id: int,
    zamestnanec_b_id: int,
    typ: str = "rozprostrit",
) -> int:
    kurzor = conn.execute(
        "INSERT INTO dvojice (zamestnanec_a_id, zamestnanec_b_id, typ) VALUES (?, ?, ?)",
        (zamestnanec_a_id, zamestnanec_b_id, typ),
    )
    conn.commit()
    return kurzor.lastrowid


def dvojice_vsechny(conn: sqlite3.Connection) -> list[Dvojice]:
    radky = conn.execute("SELECT * FROM dvojice ORDER BY id").fetchall()
    return [_dvojice_z_radku(r) for r in radky]
