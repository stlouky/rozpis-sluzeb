"""FastAPI dependency pro DB připojení + ověření DB při startu.

Nové připojení na request (žádné sdílené globální connection) - konzistentní
s db/cli.py a s konvencí "SQLite, žádný ORM" z CLAUDE.md, bez starostí o
sdílení sqlite3.Connection mezi vlákny.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request

from db import repository as repo

_LOG = logging.getLogger(__name__)

# Tabulky, které musí existovat, aby web mohl fungovat (viz db/schema.sql).
OCEKAVANE_TABULKY = frozenset({"zamestnanec", "nedostupnost", "smena", "dvojice", "uzivatel"})


def overit_databazi(cesta_db: Path) -> None:
    """Zavolá se jednou při startu webu (viz web/app.py lifespan). Web si
    DB sám nezakládá ani tiše nepřipojuje na prázdnou/starou databázi -
    incident: web a CLI měly dřív nezávislé výchozí cesty a rozjely se na
    dva různé soubory, web tak potichu běžel proti DB bez tabulky
    uzivatel, zatímco CLI mezitím zapisovalo jinam. Radši spadnout se
    srozumitelnou zprávou hned při startu, než ať to vyleze jako
    "no such table" uprostřed provozu.
    """
    if not cesta_db.exists():
        raise RuntimeError(
            f"DB neexistuje: {cesta_db}\n"
            f"Web ji sám nezakládá - nejdřív vytvoř účet přes CLI, např.:\n"
            f"  python -m db.cli --db {cesta_db} vytvorit-uzivatele <jmeno> admin"
        )

    conn = repo.pripojit(cesta_db)
    try:
        existujici = {
            radek[0]
            for radek in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    chybejici = OCEKAVANE_TABULKY - existujici
    if chybejici:
        raise RuntimeError(
            f"DB {cesta_db} existuje, ale chybí jí tabulky: {', '.join(sorted(chybejici))}.\n"
            f"Pravděpodobně jde o starší databázi z doby před přidáním těchto "
            f"tabulek do db/schema.sql. Re-inicializuj ji, nebo nastav ROZPIS_DB "
            f"(případně --db u CLI) na správný soubor."
        )

    _LOG.info("DB ověřena: %s (tabulky: %s)", cesta_db, ", ".join(sorted(existujici)))


def ziskat_pripojeni(request: Request) -> Iterator[sqlite3.Connection]:
    # Plain pripojit, ne pripojit_a_inicializovat - DB existence a schéma
    # se ověřují jednou při startu (overit_databazi výš), ne tiše
    # dovytvářejí při každém requestu.
    conn = repo.pripojit(request.app.state.cesta_db)
    try:
        yield conn
    finally:
        conn.close()
