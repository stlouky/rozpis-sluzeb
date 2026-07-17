"""Repository nad SQLite - čisté sqlite3, žádný ORM.

Zaměstnanci se nikdy nemažou (viz CLAUDE.md/NAVRH.md) - odchod se řeší
nastavením aktivni_do, historie rozpisů tak zůstává konzistentní.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .models import Dvojice, Nedostupnost, Uzivatel, Zamestnanec

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


def pripojit_a_inicializovat(cesta: str | Path) -> sqlite3.Connection:
    """Otevře DB a při prvním použití (soubor ještě neexistoval) rovnou
    inicializuje schéma. Sdíleno mezi CLI a webem, ať mají obě vstupní
    místa stejné chování při "čerstvé" databázi.
    """
    cesta_str = str(cesta)
    nova = cesta_str != ":memory:" and not Path(cesta_str).exists()
    conn = pripojit(cesta)
    if nova:
        inicializovat_schema(conn)
    return conn


def _na_datum(hodnota: str | None) -> date | None:
    return date.fromisoformat(hodnota) if hodnota else None


def _zamestnanec_z_radku(radek: sqlite3.Row) -> Zamestnanec:
    return Zamestnanec(
        id=radek["id"],
        jmeno=radek["jmeno"],
        aktivni_od=_na_datum(radek["aktivni_od"]),
        aktivni_do=_na_datum(radek["aktivni_do"]),
        stitky=radek["stitky"],
        max_smen_mesic=radek["max_smen_mesic"],
    )


def _nedostupnost_z_radku(radek: sqlite3.Row) -> Nedostupnost:
    return Nedostupnost(
        id=radek["id"],
        zamestnanec_id=radek["zamestnanec_id"],
        od=_na_datum(radek["od"]),
        do=_na_datum(radek["do"]),
        typ=radek["typ"],
        poznamka=radek["poznamka"],
        zakazana_smena=radek["zakazana_smena"],
    )


def _dvojice_z_radku(radek: sqlite3.Row) -> Dvojice:
    return Dvojice(
        id=radek["id"],
        zamestnanec_a_id=radek["zamestnanec_a_id"],
        zamestnanec_b_id=radek["zamestnanec_b_id"],
        typ=radek["typ"],
    )


def _uzivatel_z_radku(radek: sqlite3.Row) -> Uzivatel:
    return Uzivatel(
        id=radek["id"],
        jmeno=radek["jmeno"],
        heslo_hash=radek["heslo_hash"],
        role=radek["role"],
    )


# --- zaměstnanci ---

def pridat_zamestnance(
    conn: sqlite3.Connection,
    jmeno: str,
    aktivni_od: date,
    stitky: list[str] | None = None,
    max_smen_mesic: int | None = None,
) -> int:
    kurzor = conn.execute(
        "INSERT INTO zamestnanec (jmeno, aktivni_od, stitky, max_smen_mesic) VALUES (?, ?, ?, ?)",
        (jmeno, aktivni_od.isoformat(), ",".join(stitky or []), max_smen_mesic),
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


def nastavit_max_smen_mesic(
    conn: sqlite3.Connection, zamestnanec_id: int, max_smen_mesic: int | None
) -> None:
    """Nastaví (nebo zruší, pokud None) individuální strop směn/měsíc."""
    conn.execute(
        "UPDATE zamestnanec SET max_smen_mesic = ? WHERE id = ?",
        (max_smen_mesic, zamestnanec_id),
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
    zakazana_smena: str | None = None,
) -> int:
    kurzor = conn.execute(
        """
        INSERT INTO nedostupnost (zamestnanec_id, od, do, typ, poznamka, zakazana_smena)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (zamestnanec_id, od.isoformat(), do.isoformat(), typ, poznamka, zakazana_smena),
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


# --- uživatelé ---

def vytvorit_uzivatele(conn: sqlite3.Connection, jmeno: str, heslo_hash: str, role: str) -> int:
    kurzor = conn.execute(
        "INSERT INTO uzivatel (jmeno, heslo_hash, role) VALUES (?, ?, ?)",
        (jmeno, heslo_hash, role),
    )
    conn.commit()
    return kurzor.lastrowid


def uzivatel_podle_jmena(conn: sqlite3.Connection, jmeno: str) -> Uzivatel | None:
    radek = conn.execute("SELECT * FROM uzivatel WHERE jmeno = ?", (jmeno,)).fetchone()
    return _uzivatel_z_radku(radek) if radek else None


def uzivatel_podle_id(conn: sqlite3.Connection, uzivatel_id: int) -> Uzivatel | None:
    radek = conn.execute("SELECT * FROM uzivatel WHERE id = ?", (uzivatel_id,)).fetchone()
    return _uzivatel_z_radku(radek) if radek else None


def zmenit_heslo(conn: sqlite3.Connection, uzivatel_id: int, heslo_hash: str) -> None:
    conn.execute("UPDATE uzivatel SET heslo_hash = ? WHERE id = ?", (heslo_hash, uzivatel_id))
    conn.commit()
