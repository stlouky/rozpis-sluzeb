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
import time

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from db import repository as repo
from db.auth import overit_heslo
from db.models import Uzivatel

from .db import ziskat_pripojeni

NAZEV_COOKIE = "session"
MAX_STARI_SESSION_S = 7 * 24 * 3600  # 7 dní

_SESSIONS: dict[str, int] = {}

MAX_NEUSPESNYCH_POKUSU = 5
DOBA_ZABLOKOVANI_S = 5 * 60  # 5 minut

# Neúspěšné pokusy o přihlášení podle zadaného jména - in-memory, stejný
# kompromis jako _SESSIONS výš (~3 účty, jeden proces, restart vynuluje).
# Blokuje se podle JMÉNA, ne IP adresy - appka nemá před Caddy důvěryhodný
# zdroj klientské IP a při hrstce účtů líp brání proti hádání hesla ke
# konkrétnímu účtu. Vedlejší efekt: kdokoli může cíleně na pár minut
# zablokovat cizí účet posláním 5 špatných hesel - přijatelné riziko pro
# tenhle rozsah appky (viz audit).
_NEUSPESNE_POKUSY: dict[str, int] = {}
_ZABLOKOVANO_DO: dict[str, float] = {}


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


def prihlaseni_zablokovano(jmeno: str) -> bool:
    """True, když je JMÉNO (existující i neexistující - viz prihlasit)
    momentálně zablokované kvůli MAX_NEUSPESNYCH_POKUSU špatným pokusům
    po sobě."""
    do = _ZABLOKOVANO_DO.get(jmeno)
    return do is not None and time.monotonic() < do


def _zaznamenat_neuspesny_pokus(jmeno: str) -> None:
    pokusy = _NEUSPESNE_POKUSY.get(jmeno, 0) + 1
    _NEUSPESNE_POKUSY[jmeno] = pokusy
    if pokusy >= MAX_NEUSPESNYCH_POKUSU:
        _ZABLOKOVANO_DO[jmeno] = time.monotonic() + DOBA_ZABLOKOVANI_S


def _resetovat_pokusy(jmeno: str) -> None:
    _NEUSPESNE_POKUSY.pop(jmeno, None)
    _ZABLOKOVANO_DO.pop(jmeno, None)


def prihlasit(conn: sqlite3.Connection, jmeno: str, heslo: str) -> Uzivatel | None:
    """Vrátí Uzivatel při správném jménu/heslu, jinak None - i když je
    jméno správné, ale momentálně zablokované (viz prihlaseni_zablokovano).
    Počítadlo neúspěchů se vede podle zadaného jména bez ohledu na to,
    jestli účet vůbec existuje, ať z chování (ne jen z hlášky, viz
    web/app.py) nejde poznat, které jméno je platné."""
    if prihlaseni_zablokovano(jmeno):
        return None
    uzivatel = repo.uzivatel_podle_jmena(conn, jmeno)
    if uzivatel is None or not overit_heslo(heslo, uzivatel.heslo_hash):
        _zaznamenat_neuspesny_pokus(jmeno)
        return None
    _resetovat_pokusy(jmeno)
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
