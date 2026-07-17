"""FastAPI dependency pro DB připojení.

Nové připojení na request (žádné sdílené globální connection) - konzistentní
s db/cli.py a s konvencí "SQLite, žádný ORM" z CLAUDE.md, bez starostí o
sdílení sqlite3.Connection mezi vlákny.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from db import repository as repo


def ziskat_pripojeni(request: Request) -> Iterator[sqlite3.Connection]:
    conn = repo.pripojit_a_inicializovat(request.app.state.cesta_db)
    try:
        yield conn
    finally:
        conn.close()
