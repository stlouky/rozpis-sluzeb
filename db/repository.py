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

from .models import (
    Dvojice,
    NastaveniProfilu,
    Nedostupnost,
    PreskocenaSmena,
    Smena,
    Uzivatel,
    Zamestnanec,
)

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
        stav=radek["stav"],
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
    """zamestnanec.jmeno nemá v schématu UNIQUE (na rozdíl od uzivatel.jmeno),
    proto se duplicita kontroluje tady - jinak by dva zaměstnanci se stejným
    jménem prošli tiše a ulozit_rozpis (mapování jméno -> id ze Schedule)
    by pak jednoho z nich při ukládání výsledku solveru přepsal druhým,
    tedy tiše přiřadil směny špatnému člověku (nález auditu appky)."""
    if zamestnanec_podle_jmena(conn, jmeno) is not None:
        raise ValueError(f"Zaměstnanec „{jmeno}“ už existuje.")
    kurzor = conn.execute(
        "INSERT INTO zamestnanec (jmeno, aktivni_od, stitky, max_smen_mesic) VALUES (?, ?, ?, ?)",
        (jmeno, aktivni_od.isoformat(), ",".join(stitky or []), max_smen_mesic),
    )
    conn.commit()
    return kurzor.lastrowid


def deaktivovat_zamestnance(conn: sqlite3.Connection, zamestnanec_id: int, aktivni_do: date) -> None:
    """Nastaví datum odchodu. Zaměstnanec se nikdy nemaže.

    aktivni_do před aktivni_od by zaměstnance potichu vyřadilo ze VŠECH
    "aktivní" dotazů (i zpětně, viz aktivni_zamestnanci_v_obdobi) - žádné
    datum by pak nesplnilo aktivni_od <= datum <= aktivni_do zároveň
    (viz audit)."""
    zamestnanec = zamestnanec_podle_id(conn, zamestnanec_id)
    if zamestnanec is not None and aktivni_do < zamestnanec.aktivni_od:
        raise ValueError(
            f"Datum odchodu ({aktivni_do.isoformat()}) nesmí být před nástupem "
            f"({zamestnanec.aktivni_od.isoformat()})."
        )
    conn.execute(
        "UPDATE zamestnanec SET aktivni_do = ? WHERE id = ?",
        (aktivni_do.isoformat(), zamestnanec_id),
    )
    conn.commit()


def opravit_jmeno_zamestnance(conn: sqlite3.Connection, zamestnanec_id: int, jmeno: str) -> None:
    """Opraví jméno (typo/nesprávný zápis) - na rozdíl od deaktivace nejde
    o fluktuaci, jen o opravu chybného záznamu. Kontrola duplicity stejná
    jako u pridat_zamestnance (viz tam) - vynechá sebe sama, ať jde uložit
    beze změny (formulář vyplněný stávajícím jménem)."""
    existujici = zamestnanec_podle_jmena(conn, jmeno)
    if existujici is not None and existujici.id != zamestnanec_id:
        raise ValueError(f"Zaměstnanec „{jmeno}“ už existuje.")
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

# Musí sedět s CHECK na nedostupnost.typ (db/schema.sql) - kontrola tady
# existuje NAVÍC, protože bez ní by neplatná hodnota (upravený formulář v
# prohlížeči, přímý POST) spadla na syrový sqlite3.IntegrityError misto
# čitelné ValueError - routy v web/app.py chytají jen ValueError, takže by
# to skončilo HTTP 500 (nález auditu appky).
TYPY_NEDOSTUPNOSTI = ("DOV", "NEM", "OST", "SVZ", "POZADAVEK")


def _validovat_rozsah(od: date, do: date) -> None:
    """Obrácený rozsah (od > do) by se tiše uložil jako nedostupnost,
    která ve skutečnosti nic neblokuje - dny_v_mesici() na prázdném
    intervalu vrátí 0 dní, takže zaměstnanec by zůstal plně dostupný,
    přestože záznam v DB vypadá, že je pokrytý (viz audit)."""
    if od > do:
        raise ValueError(f"Datum „od“ ({od.isoformat()}) musí být <= „do“ ({do.isoformat()}).")


def _validovat_typ(typ: str) -> None:
    if typ not in TYPY_NEDOSTUPNOSTI:
        raise ValueError(
            f"Neplatný typ nedostupnosti „{typ}“, očekávám jeden z {TYPY_NEDOSTUPNOSTI}."
        )


def pridat_nedostupnost(
    conn: sqlite3.Connection,
    zamestnanec_id: int,
    od: date,
    do: date,
    typ: str,
    poznamka: str | None = None,
    zakazana_smena: str | None = None,
    stav: str = "schvaleno",
) -> int:
    _validovat_rozsah(od, do)
    _validovat_typ(typ)
    kurzor = conn.execute(
        """
        INSERT INTO nedostupnost (zamestnanec_id, od, do, typ, poznamka, zakazana_smena, stav)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (zamestnanec_id, od.isoformat(), do.isoformat(), typ, poznamka, zakazana_smena, stav),
    )
    conn.commit()
    return kurzor.lastrowid


def pridat_pozadavek(
    conn: sqlite3.Connection,
    zamestnanec_id: int,
    od: date,
    do: date,
    popis: str,
    zakazana_smena: str | None = None,
    typ: str = "POZADAVEK",
) -> int:
    """Samoobslužné podání požadavku (úkol 9b, zobecněno na typ v úkolu 9c)
    - wrapper nad pridat_nedostupnost se stav='podano'. Typ je libovolný
    z TYPY_NEDOSTUPNOSTI (nemoc/dovolená/... jde stejnou cestou jako
    obecný POZADAVEK) - rozhoduje stav, ne typ ani kdo záznam založil.
    Do solveru se nepromítne, dokud ho admin neschválí (viz
    db/bridge.py:config_pro_mesic). Odmítne zaměstnance, který k datu 'od'
    není aktivní - sdílený nahled/host účet nemá per-osobu identitu, takže
    tohle je jediná kontrola, že požadavek dává smysl (viz
    zadani-faze3-web.md)."""
    aktivni_ids = {z.id for z in aktivni_zamestnanci_v_obdobi(conn, od, od)}
    if zamestnanec_id not in aktivni_ids:
        raise ValueError("Zaměstnanec k tomuto datu není aktivní.")
    return pridat_nedostupnost(
        conn, zamestnanec_id, od, do, typ, popis, zakazana_smena, stav="podano"
    )


def schvalit_pozadavek(conn: sqlite3.Connection, pozadavek_id: int) -> None:
    conn.execute("UPDATE nedostupnost SET stav = 'schvaleno' WHERE id = ?", (pozadavek_id,))
    conn.commit()


def zamitnout_pozadavek(conn: sqlite3.Connection, pozadavek_id: int) -> None:
    """Na rozdíl od schválení (jen změna stavu) zamítnutí záznam rovnou
    maže - žádný audit trail stavu 'zamitnuto' (na přání, ať se admin
    v přehledu požadavků nemusí prokousávat dlouhým seznamem odmítnutého,
    viz diskuze k úkolu 9d)."""
    conn.execute("DELETE FROM nedostupnost WHERE id = ?", (pozadavek_id,))
    conn.commit()


def zrusit_nedostupnost(conn: sqlite3.Connection, nedostupnost_id: int) -> None:
    conn.execute("DELETE FROM nedostupnost WHERE id = ?", (nedostupnost_id,))
    conn.commit()


def nedostupnost_podle_id(conn: sqlite3.Connection, nedostupnost_id: int) -> Nedostupnost | None:
    radek = conn.execute(
        "SELECT * FROM nedostupnost WHERE id = ?", (nedostupnost_id,)
    ).fetchone()
    return _nedostupnost_z_radku(radek) if radek else None


def upravit_nedostupnost(
    conn: sqlite3.Connection,
    nedostupnost_id: int,
    od: date,
    do: date,
    typ: str,
    poznamka: str | None = None,
    zakazana_smena: str | None = None,
) -> None:
    """Přepíše existující záznam (úkol 4 přidal jen add/remove - tohle je
    "doplnit editaci" z úkolu 5, ať admin nemusí mazat a zakládat znovu
    kvůli překlepu v datu/popisu)."""
    _validovat_rozsah(od, do)
    _validovat_typ(typ)
    conn.execute(
        """
        UPDATE nedostupnost
        SET od = ?, do = ?, typ = ?, poznamka = ?, zakazana_smena = ?
        WHERE id = ?
        """,
        (od.isoformat(), do.isoformat(), typ, poznamka, zakazana_smena, nedostupnost_id),
    )
    conn.commit()


def vsechny_nedostupnosti(conn: sqlite3.Connection) -> list[Nedostupnost]:
    """Úplný výpis bez omezení na období - pro admin seznam (úkol 5), na
    rozdíl od nedostupnosti_v_obdobi níž (ta slouží config_pro_mesic/
    mřížce). Nejnovější (podle od) první."""
    radky = conn.execute("SELECT * FROM nedostupnost ORDER BY od DESC, id DESC").fetchall()
    return [_nedostupnost_z_radku(r) for r in radky]


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


def prekryvajici_nedostupnosti(
    conn: sqlite3.Connection,
    zamestnanec_id: int,
    od: date,
    do: date,
    vynechat_id: int | None = None,
) -> list[Nedostupnost]:
    """Existující nedostupnosti STEJNÉHO zaměstnance, jejichž interval se
    překrývá s [od, do] - jen pro varování ve web UI (úkol 5: "překryvy
    nedostupností: varování, ne blokace"), nic se tím neblokuje.
    vynechat_id vyřadí sebe sama při editaci (jinak by záznam vždycky
    "překrýval" sám sebe)."""
    radky = conn.execute(
        """
        SELECT * FROM nedostupnost
        WHERE zamestnanec_id = ? AND od <= ? AND do >= ?
          AND (? IS NULL OR id != ?)
        ORDER BY id
        """,
        (zamestnanec_id, do.isoformat(), od.isoformat(), vynechat_id, vynechat_id),
    ).fetchall()
    return [_nedostupnost_z_radku(r) for r in radky]


def nedostupnost_pro_den(
    conn: sqlite3.Connection, zamestnanec_id: int, datum: date
) -> Nedostupnost | None:
    """Nedostupnost pokrývající tenhle den (jestli nějaká je) - úkol 9:
    klikací úprava buňky potřebuje vědět, jestli je den součástí VÍCEdenní
    nedostupnosti (viz nastavit_nedostupnost_jednoho_dne), ne jen jaký má
    typ. Při (nepravděpodobném) překryvu víc záznamů vrátí první."""
    radek = conn.execute(
        """
        SELECT * FROM nedostupnost
        WHERE zamestnanec_id = ? AND od <= ? AND do >= ?
        ORDER BY id LIMIT 1
        """,
        (zamestnanec_id, datum.isoformat(), datum.isoformat()),
    ).fetchone()
    return _nedostupnost_z_radku(radek) if radek else None


def nastavit_nedostupnost_jednoho_dne(
    conn: sqlite3.Connection, zamestnanec_id: int, datum: date, typ: str | None
) -> None:
    """Založí/přepíše/zruší JEDNODENNÍ nedostupnost (od=do=datum) - pro
    klikací úpravu buňky v mřížce (úkol 9), ne pro běžné zadávání
    (to jde přes pridat_nedostupnost/upravit_nedostupnost na
    /admin/nedostupnosti). typ=None smaže. Nikdy nesahá na VÍCEdenní
    záznam (týdenní dovolená apod.) - takový by šlo tímhle omylem
    zkrátit/smazat po jednom kliknutí, proto raději ValueError a ať se
    to opraví na /admin/nedostupnosti."""
    existujici = nedostupnost_pro_den(conn, zamestnanec_id, datum)
    if existujici is not None and existujici.od != existujici.do:
        raise ValueError(
            f"Nedostupnost {existujici.od.isoformat()}–{existujici.do.isoformat()} "
            f"je vícedenní, nejde upravit po jednom dni - uprav ji na /admin/nedostupnosti."
        )

    if existujici is not None:
        conn.execute("DELETE FROM nedostupnost WHERE id = ?", (existujici.id,))
    if typ is not None:
        conn.execute(
            "INSERT INTO nedostupnost (zamestnanec_id, od, do, typ) VALUES (?, ?, ?, ?)",
            (zamestnanec_id, datum.isoformat(), datum.isoformat(), typ),
        )
    conn.commit()


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


def zamknout_do_dne(conn: sqlite3.Connection, rok: int, mesic: int, den: int) -> int:
    """Zamkne všechny dosud nezamčené směny s datem <= (rok, mesic, den)
    v daném měsíci. den <= 0 je no-op (není co zamknout před 1. dnem).
    Obecný stavební kámen pro zamknout_minulost (cutoff = dnešek) i pro
    ruční úpravu buňky (úkol 9: dny PŘED upraveným dnem se zamknou, ať
    přegenerování "zbytku" nešahá na už schválenou minulost)."""
    if den <= 0:
        return 0
    prvni_den = date(rok, mesic, 1)
    cutoff = date(rok, mesic, min(den, calendar.monthrange(rok, mesic)[1]))
    kurzor = conn.execute(
        "UPDATE smena SET locked = 1 WHERE datum >= ? AND datum <= ? AND locked = 0",
        (prvni_den.isoformat(), cutoff.isoformat()),
    )
    conn.commit()
    return kurzor.rowcount


def zamknout_minulost(conn: sqlite3.Connection, rok: int, mesic: int) -> int:
    """Zamkne všechny dosud nezamčené směny s datem <= dnes v daném
    měsíci (úkol 9: "zamknout minulost a odpracované směny" před
    přegenerováním, viz CLAUDE.md klíčové workflow). Pro budoucí měsíc
    (celý měsíc > dnes) je to no-op."""
    posledni_den = min(date(rok, mesic, calendar.monthrange(rok, mesic)[1]), date.today())
    prvni_den = date(rok, mesic, 1)
    if posledni_den < prvni_den:
        return 0
    return zamknout_do_dne(conn, rok, mesic, posledni_den.day)


def smena_pro_den(conn: sqlite3.Connection, zamestnanec_id: int, datum: date) -> Smena | None:
    radek = conn.execute(
        "SELECT * FROM smena WHERE zamestnanec_id = ? AND datum = ?",
        (zamestnanec_id, datum.isoformat()),
    ).fetchone()
    return _smena_z_radku(radek) if radek else None


def nastavit_smenu(
    conn: sqlite3.Connection, zamestnanec_id: int, datum: date, typ: str | None
) -> None:
    """Ručně nastaví (typ='D'/'N') nebo zruší (typ=None) jednu směnu -
    pro klikací úpravu buňky v mřížce (úkol 8), na rozdíl od
    ulozit_rozpis() níž (bulk zápis výsledku solveru). Zamčenou směnu
    NIKDY nezmění - admin ji musí nejdřív odemknout (zamknout_smeny/
    odemknout_smeny výš), stejný invariant jako u ulozit_rozpis."""
    existujici = smena_pro_den(conn, zamestnanec_id, datum)
    if existujici is not None and existujici.locked:
        raise ValueError(
            f"Směna {datum.isoformat()} je zamčená, nejde ji ručně upravit - nejdřív odemkni."
        )

    if typ is None:
        conn.execute(
            "DELETE FROM smena WHERE zamestnanec_id = ? AND datum = ?",
            (zamestnanec_id, datum.isoformat()),
        )
    elif existujici is None:
        conn.execute(
            "INSERT INTO smena (zamestnanec_id, datum, typ) VALUES (?, ?, ?)",
            (zamestnanec_id, datum.isoformat(), typ),
        )
    else:
        conn.execute("UPDATE smena SET typ = ? WHERE id = ?", (typ, existujici.id))
    conn.commit()


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


# --- nastavení (úkol 5: parametry pravidel, profily normalni/krizovy) ---

_NASTAVENI_SLOUPCE = (
    "denni_min", "denni_max", "nocni_min", "nocni_max", "max_v_rade",
    "max_smen_mesic", "plne_obsazeni", "ferovost_nocni", "ferovost_vikendy",
    "ferovost_celkem", "nekompatibilni_penalizace",
)


def nastaveni_pro_profil(conn: sqlite3.Connection, profil: str) -> NastaveniProfilu | None:
    """None, dokud admin daný profil poprvé neuloží - volající (db/bridge.py)
    to bere jako signál použít config.yaml (viz schema.sql).

    Tabulka nastaveni je nová (úkol 5) - na existující data/rozpis.db bez
    ruční migrace (viz STAV-FAZE3.md) ještě nemusí vůbec existovat. Web ji
    vyžaduje už při startu (web/db.py:OCEKAVANE_TABULKY), ale CLI generuj
    overit_databazi nevolá (nikdy nevolalo) - "tabulka chybí" tak musí
    spadnout na stejné None jako "řádek chybí", ať CLI proti nemigrované
    DB dál funguje (fallback na config.yaml), místo aby spadlo na syrový
    OperationalError.
    """
    try:
        radek = conn.execute(
            "SELECT * FROM nastaveni WHERE profil = ?", (profil,)
        ).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            raise
        return None
    if radek is None:
        return None
    return NastaveniProfilu(profil=radek["profil"], **{s: radek[s] for s in _NASTAVENI_SLOUPCE})


def ulozit_nastaveni(conn: sqlite3.Connection, nastaveni: NastaveniProfilu) -> None:
    """Upsert podle profilu (PRIMARY KEY) - první uložení daného profilu
    ho založí, další jen přepíšou hodnoty."""
    sloupce = ("profil",) + _NASTAVENI_SLOUPCE
    hodnoty = [getattr(nastaveni, s) for s in sloupce]
    conn.execute(
        f"""
        INSERT INTO nastaveni ({", ".join(sloupce)})
        VALUES ({", ".join("?" * len(sloupce))})
        ON CONFLICT (profil) DO UPDATE SET
        {", ".join(f"{s} = excluded.{s}" for s in _NASTAVENI_SLOUPCE)}
        """,
        hodnoty,
    )
    conn.commit()
