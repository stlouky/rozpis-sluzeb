"""Repository nad SQLite - čisté sqlite3, žádný ORM.

Zaměstnanci se nikdy nemažou (viz CLAUDE.md/NAVRH.md) - odchod se řeší
nastavením aktivni_do, historie rozpisů tak zůstává konzistentní.
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date
from pathlib import Path

from solver.schedule import Schedule

from .models import Dvojice, Nedostupnost, PreskocenaSmena, Smena, Uzivatel, Zamestnanec

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
    if nova:
        # výchozí cesta je data/rozpis.db (viz db/cesta.py) - na čerstvém
        # checkoutu adresář data/ ještě nemusí existovat
        Path(cesta_str).parent.mkdir(parents=True, exist_ok=True)
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
        zakaz_smeny=radek["zakaz_smeny"],
        max_za_sebou=radek["max_za_sebou"],
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


def _smena_z_radku(radek: sqlite3.Row) -> Smena:
    return Smena(
        id=radek["id"],
        zamestnanec_id=radek["zamestnanec_id"],
        datum=_na_datum(radek["datum"]),
        typ=radek["typ"],
        locked=bool(radek["locked"]),
        stav=radek["stav"],
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


def nastavit_zakaz_smeny(
    conn: sqlite3.Connection, zamestnanec_id: int, zakaz_smeny: str | None
) -> None:
    """Nastaví (nebo zruší, pokud None) trvalý zákaz typu směny ('D'/'N') -
    platí pro všechny měsíce, na rozdíl od nedostupnost.zakazana_smena."""
    conn.execute(
        "UPDATE zamestnanec SET zakaz_smeny = ? WHERE id = ?",
        (zakaz_smeny, zamestnanec_id),
    )
    conn.commit()


def nastavit_max_za_sebou(
    conn: sqlite3.Connection, zamestnanec_id: int, max_za_sebou: int | None
) -> None:
    """Nastaví (nebo zruší, pokud None) osobní strop směn v řadě - přebije
    společné pravidla.max_v_rade jen pro tohohle člověka."""
    conn.execute(
        "UPDATE zamestnanec SET max_za_sebou = ? WHERE id = ?",
        (max_za_sebou, zamestnanec_id),
    )
    conn.commit()


def zamestnanec_podle_jmena(conn: sqlite3.Connection, jmeno: str) -> Zamestnanec | None:
    radek = conn.execute("SELECT * FROM zamestnanec WHERE jmeno = ?", (jmeno,)).fetchone()
    return _zamestnanec_z_radku(radek) if radek else None


def zamestnanec_podle_id(conn: sqlite3.Connection, zamestnanec_id: int) -> Zamestnanec | None:
    radek = conn.execute(
        "SELECT * FROM zamestnanec WHERE id = ?", (zamestnanec_id,)
    ).fetchone()
    return _zamestnanec_z_radku(radek) if radek else None


def ma_nejakou_smenu(conn: sqlite3.Connection, zamestnanec_id: int) -> bool:
    """True, pokud má zaměstnanec aspoň jednu uloženou směnu (v jakémkoli
    měsíci) - řídí, jestli má admin ve web UI vůbec nabídnout tvrdé
    smazání (viz smazat_zamestnance), ne jen jako informace navíc."""
    radek = conn.execute(
        "SELECT 1 FROM smena WHERE zamestnanec_id = ? LIMIT 1", (zamestnanec_id,)
    ).fetchone()
    return radek is not None


def smazat_zamestnance(conn: sqlite3.Connection, zamestnanec_id: int) -> None:
    """Tvrdé smazání záznamu - jen pro omyl při zakládání (viz
    db/schema.sql úvodní komentář: zaměstnanci se JINAK nikdy nemažou,
    odchod řeší deaktivovat_zamestnance). Cizí klíče (PRAGMA
    foreign_keys=ON, viz pripojit()) smazání samy zablokují, pokud na
    zaměstnance odkazuje směna/nedostupnost/dvojice - tady se to jen
    převádí na čitelnou chybu pro volajícího (web/CLI)."""
    try:
        conn.execute("DELETE FROM zamestnanec WHERE id = ?", (zamestnanec_id,))
    except sqlite3.IntegrityError as e:
        raise ValueError(
            f"Zaměstnance (id={zamestnanec_id}) nejde smazat - existují na něj "
            f"navázané záznamy (směna/nedostupnost/dvojice). Použij deaktivaci."
        ) from e
    conn.commit()


def vsichni_zamestnanci(conn: sqlite3.Connection) -> list[Zamestnanec]:
    """Úplně všichni zaměstnanci vč. bývalých (na rozdíl od aktivni_zamestnanci*
    níž) - pro administraci ("i bývalí", úkol 4) a párování jmen při importu."""
    radky = conn.execute("SELECT * FROM zamestnanec ORDER BY id").fetchall()
    return [_zamestnanec_z_radku(r) for r in radky]


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


# --- směny ---

def _smazat_nezamcene(conn: sqlite3.Connection, od: date, do: date) -> None:
    """Bez commitu - interní stavební kámen pro ulozit_rozpis() a
    smazat_nezamcene_v_obdobi(), ať se v jedné transakci nedělá zbytečně
    víc commitů."""
    conn.execute(
        "DELETE FROM smena WHERE datum >= ? AND datum <= ? AND locked = 0",
        (od.isoformat(), do.isoformat()),
    )


def smazat_nezamcene_v_obdobi(conn: sqlite3.Connection, od: date, do: date) -> None:
    """Smaže nezamčené směny v intervalu [od, do] (včetně) - zamčené
    zůstávají netknuté. Základ pro přegenerování zbytku měsíce (úkol 9)."""
    _smazat_nezamcene(conn, od, do)
    conn.commit()


def smeny_v_mesici(conn: sqlite3.Connection, rok: int, mesic: int) -> list[Smena]:
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])
    radky = conn.execute(
        "SELECT * FROM smena WHERE datum >= ? AND datum <= ? ORDER BY datum, zamestnanec_id",
        (prvni_den.isoformat(), posledni_den.isoformat()),
    ).fetchall()
    return [_smena_z_radku(r) for r in radky]


def zamknout_smeny(conn: sqlite3.Connection, seznam_id: list[int]) -> None:
    conn.executemany("UPDATE smena SET locked = 1 WHERE id = ?", [(i,) for i in seznam_id])
    conn.commit()


def odemknout_smeny(conn: sqlite3.Connection, seznam_id: list[int]) -> None:
    conn.executemany("UPDATE smena SET locked = 0 WHERE id = ?", [(i,) for i in seznam_id])
    conn.commit()


def ulozit_rozpis(conn: sqlite3.Connection, schedule: Schedule) -> list[PreskocenaSmena]:
    """Uloží vygenerovaný Schedule (solver/schedule.py) do DB: smaže
    nezamčené směny daného měsíce a zapíše nové. Zamčené směny se NIKDY
    nepřepíšou ani nesmažou - pokud schedule pro zamčený (zaměstnanec,
    den) přináší jinou hodnotu, tenhle záznam se prostě přeskočí (locked
    vyhrává, viz CLAUDE.md klíčové workflow: zamknout minulost/odpracované
    směny, přegenerovat jen zbytek) - vrátí seznam takových konfliktů, ať
    má volající (web/CLI) co ukázat, ne jen tichou ztrátu dat.

    Celá operace (smazání + zápis) běží v jedné transakci - při jakékoli
    chybě uprostřed se nic nepropíše (rollback), DB zůstane přesně tam,
    kde byla před voláním.
    """
    prvni_den = date(schedule.rok, schedule.mesic, 1)
    posledni_den = date(schedule.rok, schedule.mesic, schedule.pocet_dni)

    try:
        _smazat_nezamcene(conn, prvni_den, posledni_den)

        zamestnanec_id_podle_jmena = {
            radek["jmeno"]: radek["id"]
            for radek in conn.execute("SELECT id, jmeno FROM zamestnanec").fetchall()
        }
        zamcene_dny = {
            (radek["zamestnanec_id"], radek["datum"]): radek["typ"]
            for radek in conn.execute(
                "SELECT zamestnanec_id, datum, typ FROM smena"
                " WHERE locked = 1 AND datum >= ? AND datum <= ?",
                (prvni_den.isoformat(), posledni_den.isoformat()),
            ).fetchall()
        }

        preskocene: list[PreskocenaSmena] = []
        for (jmeno, den), typ in schedule.smeny.items():
            zamestnanec_id = zamestnanec_id_podle_jmena.get(jmeno)
            if zamestnanec_id is None:
                continue  # neznámé jméno - nemělo by nastat, radši nezahodit zbytek zápisu
            datum = date(schedule.rok, schedule.mesic, den).isoformat()
            puvodni_typ = zamcene_dny.get((zamestnanec_id, datum))
            if puvodni_typ is not None:
                # locked směna se nikdy nepřepisuje - i kdyby nový typ byl
                # stejný jako ten zamčený, jde o no-op, ne o konflikt
                if puvodni_typ != typ:
                    preskocene.append(
                        PreskocenaSmena(
                            zamestnanec_id=zamestnanec_id,
                            jmeno=jmeno,
                            datum=date.fromisoformat(datum),
                            puvodni_typ=puvodni_typ,
                            novy_typ=typ,
                        )
                    )
                continue
            conn.execute(
                "INSERT INTO smena (zamestnanec_id, datum, typ) VALUES (?, ?, ?)",
                (zamestnanec_id, datum, typ),
            )
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()

    return preskocene


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
