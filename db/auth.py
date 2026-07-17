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
    return bcrypt.checkpw(heslo.encode(), heslo_hash.encode())
