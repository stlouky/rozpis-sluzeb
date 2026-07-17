"""Přihlašování: server-side session + FastAPI dependencies pro autorizaci.

Cookie nese jen podepsaný (itsdangerous), neuhodnutelný token - samotná
session (token -> uzivatel_id) žije výhradně na serveru, ne v cookie
(viz CLAUDE.md, bezpečnostní invarianty: "server-side session").

Session store je jednoduchý in-memory dict - odpovídá rozsahu appky
(~3 účty, jeden uvicorn proces, viz CLAUDE.md "Stack — záměrně minimální").
Restart procesu odhlásí všechny, což je přijatelný kompromis za tuhle
jednoduchost.
"""

from __future__ import annotations

import secrets
import sqlite3

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from db import repository as repo
from db.auth import overit_heslo
from db.models import Uzivatel

from .db import ziskat_pripojeni

NAZEV_COOKIE = "session"
MAX_STARI_SESSION_S = 7 * 24 * 3600  # 7 dní

_SESSIONS: dict[str, int] = {}


def _serializer(tajny_klic: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(tajny_klic, salt="rozpis-session")


def vytvorit_session(uzivatel_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = uzivatel_id
    return token


def zrusit_session(token: str) -> None:
    _SESSIONS.pop(token, None)


def podepsat_token(token: str, tajny_klic: str) -> str:
    return _serializer(tajny_klic).dumps(token)


def rozbalit_token(podepsany: str, tajny_klic: str) -> str | None:
    try:
        return _serializer(tajny_klic).loads(podepsany, max_age=MAX_STARI_SESSION_S)
    except (BadSignature, SignatureExpired):
        return None


def prihlasit(conn: sqlite3.Connection, jmeno: str, heslo: str) -> Uzivatel | None:
    uzivatel = repo.uzivatel_podle_jmena(conn, jmeno)
    if uzivatel is None or not overit_heslo(heslo, uzivatel.heslo_hash):
        return None
    return uzivatel


def _token_ze_session_cookie(request: Request) -> str | None:
    podepsany = request.cookies.get(NAZEV_COOKIE)
    if not podepsany:
        return None
    return rozbalit_token(podepsany, request.app.state.tajny_klic)


def _presmerovat_na_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/login"},
    )


def odhlasit(request: Request) -> None:
    """Zruší server-side session patřící k session cookie z requestu (no-op,
    pokud žádná platná session neexistuje)."""
    token = _token_ze_session_cookie(request)
    if token:
        zrusit_session(token)


def vyzadovat_prihlaseni(
    request: Request, conn: sqlite3.Connection = Depends(ziskat_pripojeni)
) -> Uzivatel:
    token = _token_ze_session_cookie(request)
    uzivatel_id = _SESSIONS.get(token) if token else None
    if uzivatel_id is None:
        raise _presmerovat_na_login()
    uzivatel = repo.uzivatel_podle_id(conn, uzivatel_id)
    if uzivatel is None:
        raise _presmerovat_na_login()
    return uzivatel


def vyzadovat_admina(uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni)) -> Uzivatel:
    if uzivatel.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Vyžaduje roli admin"
        )
    return uzivatel
