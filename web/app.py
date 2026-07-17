"""FastAPI aplikace - kostra webu + přihlášení (úkol 1).

Server-side rendering přes Jinja2, žádné SPA (viz CLAUDE.md). Mřížka
rozpisu, správa zaměstnanců a další funkčnost přibudou v dalších úkolech
(zadani-faze3-web.md) - tady je jen kostra a login/logout.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db.models import Uzivatel

from .auth import (
    MAX_STARI_SESSION_S,
    NAZEV_COOKIE,
    odhlasit,
    podepsat_token,
    prihlasit,
    vyzadovat_admina,
    vyzadovat_prihlaseni,
    vytvorit_session,
)
from .db import ziskat_pripojeni

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT.parent / "rozpis.db"

app = FastAPI(title="Rozpis služeb")
app.state.cesta_db = Path(os.environ.get("ROZPIS_DB", str(DEFAULT_DB)))
# Bez explicitního tajného klíče (produkce, viz úkol 10 - deploy) se vygeneruje
# nový při každém startu - restart tak odhlásí všechny (stejný kompromis jako
# in-memory session store, viz web/auth.py).
app.state.tajny_klic = os.environ.get("ROZPIS_TAJNY_KLIC") or secrets.token_hex(32)

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
sablony = Jinja2Templates(directory=str(ROOT / "sablony"))


@app.get("/login")
def login_formular(request: Request):
    return sablony.TemplateResponse(request, "login.html", {"chyba": None})


@app.post("/login")
def login_odeslani(
    request: Request,
    jmeno: str = Form(...),
    heslo: str = Form(...),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    uzivatel = prihlasit(conn, jmeno, heslo)
    if uzivatel is None:
        return sablony.TemplateResponse(
            request,
            "login.html",
            {"chyba": "Špatné jméno nebo heslo."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = vytvorit_session(uzivatel.id)
    odpoved = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    odpoved.set_cookie(
        NAZEV_COOKIE,
        podepsat_token(token, request.app.state.tajny_klic),
        max_age=MAX_STARI_SESSION_S,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return odpoved


@app.post("/logout")
def logout(request: Request, uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni)):
    odhlasit(request)
    odpoved = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    odpoved.delete_cookie(NAZEV_COOKIE)
    return odpoved


@app.get("/")
def index(request: Request, uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni)):
    return sablony.TemplateResponse(request, "index.html", {"uzivatel": uzivatel})


@app.get("/admin")
def admin_uvod(request: Request, uzivatel: Uzivatel = Depends(vyzadovat_admina)):
    return sablony.TemplateResponse(request, "admin.html", {"uzivatel": uzivatel})
