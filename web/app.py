"""FastAPI aplikace - kostra webu + přihlášení (úkol 1).

Server-side rendering přes Jinja2, žádné SPA (viz CLAUDE.md). Mřížka
rozpisu, správa zaměstnanců a další funkčnost přibudou v dalších úkolech
(zadani-faze3-web.md) - tady je jen kostra a login/logout.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db.cesta import vychozi_cesta_db
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
from .db import overit_databazi, ziskat_pripojeni
from .mrizka import sestavit_mrizku

ROOT = Path(__file__).resolve().parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Ověří DB existenci + schéma JEDNOU při startu, ať web nikdy tiše
    # neběží proti prázdné/staré databázi (viz web/db.py:overit_databazi).
    overit_databazi(app.state.cesta_db)
    yield


app = FastAPI(title="Rozpis služeb", lifespan=_lifespan)
app.state.cesta_db = vychozi_cesta_db()
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
    odpoved = RedirectResponse(url="/rozpis", status_code=status.HTTP_303_SEE_OTHER)
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
def index(uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni)):
    return RedirectResponse(url="/rozpis", status_code=status.HTTP_303_SEE_OTHER)


def _rozlozit_mesic(mesic: str | None) -> tuple[int, int]:
    """'YYYY-MM' -> (rok, měsíc). Chybějící nebo nevalidní hodnota tiše
    spadne na aktuální měsíc - jde o pohodlnou výchozí stránku, ne API
    s nutností hlásit chybu na překlep v URL."""
    if mesic:
        try:
            rok_str, mesic_str = mesic.split("-")
            rok, mes = int(rok_str), int(mesic_str)
            if 1 <= mes <= 12:
                return rok, mes
        except ValueError:
            pass
    dnes = date.today()
    return dnes.year, dnes.month


@app.get("/rozpis")
def rozpis_mesice(
    request: Request,
    mesic: str | None = None,
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    je_admin = uzivatel.role == "admin"
    if je_admin:
        rok, mes = _rozlozit_mesic(mesic)
    else:
        # role nahled vidí JEN aktuální měsíc - parametr mesic se ignoruje
        # i kdyby ho někdo ručně přidal do URL (viz zadani-faze3-web.md)
        dnes = date.today()
        rok, mes = dnes.year, dnes.month

    mrizka = sestavit_mrizku(conn, rok, mes, je_admin=je_admin)

    predchozi_rok, predchozi_mes = (rok - 1, 12) if mes == 1 else (rok, mes - 1)
    dalsi_rok, dalsi_mes = (rok + 1, 1) if mes == 12 else (rok, mes + 1)

    return sablony.TemplateResponse(
        request,
        "mrizka.html",
        {
            "uzivatel": uzivatel,
            "je_admin": je_admin,
            "mrizka": mrizka,
            "predchozi_mesic": f"{predchozi_rok}-{predchozi_mes:02d}",
            "dalsi_mesic": f"{dalsi_rok}-{dalsi_mes:02d}",
        },
    )


@app.get("/admin")
def admin_uvod(request: Request, uzivatel: Uzivatel = Depends(vyzadovat_admina)):
    return sablony.TemplateResponse(request, "admin.html", {"uzivatel": uzivatel})
