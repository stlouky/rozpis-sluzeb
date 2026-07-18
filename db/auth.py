"""Hashování a ověřování hesel (bcrypt).

Sdílené mezi CLI (db/cli.py) a webem (web/auth.py) - hashování je čistě
kryptografická operace bez závislosti na FastAPI/session vrstvě, proto
žije v db/, ne ve web/ (viz CLAUDE.md: web je tenká vrstva nad db/).
"""

from __future__ import annotations

import bcrypt


def hashovat_heslo(heslo: str) -> str:
    return bcrypt.hashpw(heslo.encode(), bcrypt.gensalt()).decode()


def overit_heslo(heslo: str, heslo_hash: str) -> bool:
    """False i pro heslo delší než 72 bajtů (bcrypt limit) - bcrypt 4.1+ na
    to místo tichého oříznutí vyhazuje ValueError. Bez try/except by
    nepřihlášený uživatel dlouhým heslem na /login shodil endpoint na
    HTTP 500 místo "špatné heslo" (nález auditu appky)."""
    try:
        return bcrypt.checkpw(heslo.encode(), heslo_hash.encode())
    except ValueError:
        return False
