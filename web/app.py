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

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import repository as repo
from db.bridge import config_pro_mesic
from db.cesta import vychozi_cesta_db
from db.models import NastaveniProfilu, Nedostupnost, Uzivatel, Zamestnanec
from solver.core import NelzeSestavitError, generate_schedule

from .auth import (
    MAX_STARI_SESSION_S,
    NAZEV_COOKIE,
    odhlasit,
    podepsat_token,
    prihlasit,
    prihlaseni_zablokovano,
    vyzadovat_admina,
    vyzadovat_prihlaseni,
    vytvorit_session,
)
from .db import overit_databazi, ziskat_pripojeni
from .mrizka import NAZEV_NEDOSTUPNOSTI, sestavit_mrizku

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
        # Zablokované jméno se hlásí zvlášť (ne jako "špatné heslo") - jde
        # to bezpečně, protože se blokuje stejně bez ohledu na to, jestli
        # jméno vůbec existuje (viz web/auth.py:prihlaseni_zablokovano),
        # takže tahle hláška sama o sobě neprozradí platnost jména.
        chyba = (
            "Příliš mnoho neúspěšných pokusů, zkuste to znovu za pár minut."
            if prihlaseni_zablokovano(jmeno)
            else "Špatné jméno nebo heslo."
        )
        return sablony.TemplateResponse(
            request,
            "login.html",
            {"chyba": chyba},
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


def _vykreslit_rozpis(
    request: Request,
    conn: sqlite3.Connection,
    uzivatel: Uzivatel,
    rok: int,
    mes: int,
    je_admin: bool,
    **extra,
):
    """Sestaví a vykreslí mřížku měsíce - sdíleno mezi GET /rozpis (běžné
    zobrazení) a POST /rozpis/generovat (výsledek/chyba generování se
    ukazuje na téže stránce, ne na zvláštní), ať se mřížka nesestavuje
    na dvou místech dvakrát jinak."""
    mrizka = sestavit_mrizku(conn, rok, mes, je_admin=je_admin)
    predchozi_rok, predchozi_mes = (rok - 1, 12) if mes == 1 else (rok, mes - 1)
    dalsi_rok, dalsi_mes = (rok + 1, 1) if mes == 12 else (rok, mes + 1)
    kontext = {
        "uzivatel": uzivatel,
        "je_admin": je_admin,
        "mrizka": mrizka,
        "predchozi_mesic": f"{predchozi_rok}-{predchozi_mes:02d}",
        "dalsi_mesic": f"{dalsi_rok}-{dalsi_mes:02d}",
        "vygenerovano": False,
        "generovani_status": None,
        "generovani_cas": None,
        "preskoceno": 0,
        "chyba_generovani": None,
        "profil_generovani": None,
        "profil_generovani_nazev": None,
    }
    kontext.update(extra)
    return sablony.TemplateResponse(request, "mrizka.html", kontext)


@app.get("/rozpis")
def rozpis_mesice(
    request: Request,
    mesic: str | None = None,
    vygenerovano: bool = False,
    generovani_status: str | None = None,
    generovani_cas: float | None = None,
    preskoceno: int = 0,
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

    return _vykreslit_rozpis(
        request, conn, uzivatel, rok, mes, je_admin,
        vygenerovano=vygenerovano,
        generovani_status=generovani_status,
        generovani_cas=generovani_cas,
        preskoceno=preskoceno,
    )


# --- úkol 6: admin - VYGENEROVAT ---

GENEROVANI_TIME_LIMIT_S = 30.0
# Pevný seed vynucuje num_search_workers=1 (viz solver/core.py) - server
# sdílí 2 vCPU s rbscannerem, úloha je malá, takže rychlost neutrpí; vedlejší
# efekt je deterministický výsledek, stejně jako v testech (viz zadani-faze3-web.md).
GENEROVANI_SEED = 42

PROFILY_NAZVY = {"normalni": "normální", "krizovy": "krizový"}


@app.post("/rozpis/generovat")
def rozpis_generovat(
    request: Request,
    mesic: str = Form(...),
    profil: str = Form("normalni"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    rok, mes = _rozlozit_mesic(mesic)
    config = config_pro_mesic(conn, rok, mes, profil=profil)
    try:
        schedule = generate_schedule(
            config, time_limit_s=GENEROVANI_TIME_LIMIT_S, random_seed=GENEROVANI_SEED
        )
    except NelzeSestavitError as e:
        # Nesplnitelnost se ukáže rovnou na mřížce (ne HTTP 500) - viz
        # solver.core._diagnostikuj_nesplnitelnost pro obsah e.duvody.
        return _vykreslit_rozpis(
            request, conn, uzivatel, rok, mes, je_admin=True,
            chyba_generovani=e.duvody,
            profil_generovani=profil,
            profil_generovani_nazev=PROFILY_NAZVY.get(profil, profil),
        )

    preskocene = repo.ulozit_rozpis(conn, schedule)
    url = (
        f"/rozpis?mesic={rok}-{mes:02d}&vygenerovano=1"
        f"&generovani_status={schedule.status}&generovani_cas={schedule.cas_reseni:.1f}"
        f"&preskoceno={len(preskocene)}"
    )
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin")
def admin_uvod(request: Request, uzivatel: Uzivatel = Depends(vyzadovat_admina)):
    return sablony.TemplateResponse(request, "admin.html", {"uzivatel": uzivatel})


# --- úkol 4: admin - správa zaměstnanců ---

STITEK_FYZICKA_VYPOMOC = "fyzicka_vypomoc"


@app.get("/admin/zamestnanci")
def admin_zamestnanci_seznam(
    request: Request,
    vsichni: bool = False,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    zamestnanci = (
        repo.vsichni_zamestnanci(conn)
        if vsichni
        else repo.aktivni_zamestnanci(conn, date.today())
    )
    return sablony.TemplateResponse(
        request,
        "admin_zamestnanci.html",
        {"uzivatel": uzivatel, "zamestnanci": zamestnanci, "vsichni": vsichni},
    )


@app.get("/admin/zamestnanci/novy")
def admin_zamestnanec_novy_formular(
    request: Request,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    return sablony.TemplateResponse(
        request,
        "admin_zamestnanec_novy.html",
        {
            "uzivatel": uzivatel,
            "chyba": None,
            "dnes": date.today().isoformat(),
            # Možní partneři pro neslučitelnou dvojici - jen dnes aktivní,
            # ať formulář nenabízí dávno odešlé lidi (viz úkol 4 zadání:
            # "při nástupu nového člověka se vše nastaví na jednom místě").
            "mozni_partneri": repo.aktivni_zamestnanci(conn, date.today()),
        },
    )


@app.post("/admin/zamestnanci/novy")
def admin_zamestnanec_novy_odeslani(
    request: Request,
    jmeno: str = Form(...),
    aktivni_od: date = Form(...),
    max_smen_mesic: str = Form(""),
    fyzicka_vypomoc: bool = Form(False),
    dvojice_s: list[int] = Form([]),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    if not jmeno.strip():
        return sablony.TemplateResponse(
            request,
            "admin_zamestnanec_novy.html",
            {
                "uzivatel": uzivatel,
                "chyba": "Jméno je povinné.",
                "dnes": date.today().isoformat(),
                "mozni_partneri": repo.aktivni_zamestnanci(conn, date.today()),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    stitky = [STITEK_FYZICKA_VYPOMOC] if fyzicka_vypomoc else []
    strop = int(max_smen_mesic) if max_smen_mesic.strip() else None
    novy_id = repo.pridat_zamestnance(conn, jmeno.strip(), aktivni_od, stitky, strop)
    for partner_id in dvojice_s:
        repo.pridat_dvojici(conn, novy_id, partner_id)

    return RedirectResponse(url="/admin/zamestnanci", status_code=status.HTTP_303_SEE_OTHER)


def _zamestnanec_nebo_404(conn: sqlite3.Connection, zamestnanec_id: int) -> Zamestnanec:
    zamestnanec = repo.zamestnanec_podle_id(conn, zamestnanec_id)
    if zamestnanec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zaměstnanec neexistuje")
    return zamestnanec


@app.get("/admin/zamestnanci/{zamestnanec_id}/upravit")
def admin_zamestnanec_upravit_formular(
    request: Request,
    zamestnanec_id: int,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    zamestnanec = _zamestnanec_nebo_404(conn, zamestnanec_id)
    return sablony.TemplateResponse(
        request,
        "admin_zamestnanec_upravit.html",
        {
            "uzivatel": uzivatel,
            "zamestnanec": zamestnanec,
            "ma_smenu": repo.ma_nejakou_smenu(conn, zamestnanec_id),
            "chyba": None,
        },
    )


@app.post("/admin/zamestnanci/{zamestnanec_id}/upravit-jmeno")
def admin_zamestnanec_upravit_jmeno(
    zamestnanec_id: int,
    jmeno: str = Form(...),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    _zamestnanec_nebo_404(conn, zamestnanec_id)
    if jmeno.strip():
        repo.opravit_jmeno_zamestnance(conn, zamestnanec_id, jmeno.strip())
    return RedirectResponse(
        url=f"/admin/zamestnanci/{zamestnanec_id}/upravit", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/admin/zamestnanci/{zamestnanec_id}/deaktivovat")
def admin_zamestnanec_deaktivovat(
    request: Request,
    zamestnanec_id: int,
    aktivni_do: date = Form(...),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    zamestnanec = _zamestnanec_nebo_404(conn, zamestnanec_id)
    try:
        repo.deaktivovat_zamestnance(conn, zamestnanec_id, aktivni_do)
    except ValueError as e:
        return sablony.TemplateResponse(
            request,
            "admin_zamestnanec_upravit.html",
            {
                "uzivatel": uzivatel,
                "zamestnanec": zamestnanec,
                "ma_smenu": repo.ma_nejakou_smenu(conn, zamestnanec_id),
                "chyba": str(e),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(url="/admin/zamestnanci", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/zamestnanci/{zamestnanec_id}/smazat")
def admin_zamestnanec_smazat(
    request: Request,
    zamestnanec_id: int,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    zamestnanec = _zamestnanec_nebo_404(conn, zamestnanec_id)
    try:
        repo.smazat_zamestnance(conn, zamestnanec_id)
    except ValueError as e:
        return sablony.TemplateResponse(
            request,
            "admin_zamestnanec_upravit.html",
            {
                "uzivatel": uzivatel,
                "zamestnanec": zamestnanec,
                "ma_smenu": repo.ma_nejakou_smenu(conn, zamestnanec_id),
                "chyba": str(e),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(url="/admin/zamestnanci", status_code=status.HTTP_303_SEE_OTHER)


# --- úkol 5: admin - nedostupnosti + parametry pravidel ---


def _nedostupnost_nebo_404(conn: sqlite3.Connection, nedostupnost_id: int) -> Nedostupnost:
    nedostupnost = repo.nedostupnost_podle_id(conn, nedostupnost_id)
    if nedostupnost is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nedostupnost neexistuje")
    return nedostupnost


def _bez_smeny(zakazana_smena: str) -> str | None:
    """Formulářová hodnota '' (celý den) -> None, jinak 'D'/'N' beze změny."""
    return zakazana_smena if zakazana_smena in ("D", "N") else None


@app.get("/admin/nedostupnosti")
def admin_nedostupnosti_seznam(
    request: Request,
    varovani: int = 0,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    jmeno_podle_id = {z.id: z.jmeno for z in repo.vsichni_zamestnanci(conn)}
    return sablony.TemplateResponse(
        request,
        "admin_nedostupnosti.html",
        {
            "uzivatel": uzivatel,
            "nedostupnosti": repo.vsechny_nedostupnosti(conn),
            "jmeno_podle_id": jmeno_podle_id,
            "nazvy_typu": NAZEV_NEDOSTUPNOSTI,
            "varovani": varovani,
        },
    )


@app.get("/admin/nedostupnosti/nova")
def admin_nedostupnost_nova_formular(
    request: Request,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    return sablony.TemplateResponse(
        request,
        "admin_nedostupnost_nova.html",
        {
            "uzivatel": uzivatel,
            "chyba": None,
            "zamestnanci": repo.aktivni_zamestnanci(conn, date.today()),
            "typy": NAZEV_NEDOSTUPNOSTI,
        },
    )


@app.post("/admin/nedostupnosti/nova")
def admin_nedostupnost_nova_odeslani(
    request: Request,
    zamestnanec_id: int = Form(...),
    od: date = Form(...),
    do: date = Form(...),
    typ: str = Form(...),
    poznamka: str = Form(""),
    zakazana_smena: str = Form(""),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    try:
        nova_id = repo.pridat_nedostupnost(
            conn, zamestnanec_id, od, do, typ, poznamka.strip() or None, _bez_smeny(zakazana_smena)
        )
    except ValueError as e:
        return sablony.TemplateResponse(
            request,
            "admin_nedostupnost_nova.html",
            {
                "uzivatel": uzivatel,
                "chyba": str(e),
                "zamestnanci": repo.aktivni_zamestnanci(conn, date.today()),
                "typy": NAZEV_NEDOSTUPNOSTI,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    # Překryv jen jako varování, ne blokace (viz úkol 5 zadání) - záznam
    # je uložený, i když se s jiným časově kryje.
    prekryv = repo.prekryvajici_nedostupnosti(conn, zamestnanec_id, od, do, vynechat_id=nova_id)
    url = "/admin/nedostupnosti"
    if prekryv:
        url += f"?varovani={len(prekryv)}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/nedostupnosti/{nedostupnost_id}/upravit")
def admin_nedostupnost_upravit_formular(
    request: Request,
    nedostupnost_id: int,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    nedostupnost = _nedostupnost_nebo_404(conn, nedostupnost_id)
    zamestnanec = repo.zamestnanec_podle_id(conn, nedostupnost.zamestnanec_id)
    return sablony.TemplateResponse(
        request,
        "admin_nedostupnost_upravit.html",
        {
            "uzivatel": uzivatel,
            "chyba": None,
            "nedostupnost": nedostupnost,
            "zamestnanec": zamestnanec,
            "typy": NAZEV_NEDOSTUPNOSTI,
        },
    )


@app.post("/admin/nedostupnosti/{nedostupnost_id}/upravit")
def admin_nedostupnost_upravit_odeslani(
    request: Request,
    nedostupnost_id: int,
    od: date = Form(...),
    do: date = Form(...),
    typ: str = Form(...),
    poznamka: str = Form(""),
    zakazana_smena: str = Form(""),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    nedostupnost = _nedostupnost_nebo_404(conn, nedostupnost_id)
    try:
        repo.upravit_nedostupnost(
            conn, nedostupnost_id, od, do, typ, poznamka.strip() or None, _bez_smeny(zakazana_smena)
        )
    except ValueError as e:
        zamestnanec = repo.zamestnanec_podle_id(conn, nedostupnost.zamestnanec_id)
        return sablony.TemplateResponse(
            request,
            "admin_nedostupnost_upravit.html",
            {
                "uzivatel": uzivatel,
                "chyba": str(e),
                "nedostupnost": nedostupnost,
                "zamestnanec": zamestnanec,
                "typy": NAZEV_NEDOSTUPNOSTI,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    prekryv = repo.prekryvajici_nedostupnosti(
        conn, nedostupnost.zamestnanec_id, od, do, vynechat_id=nedostupnost_id
    )
    url = "/admin/nedostupnosti"
    if prekryv:
        url += f"?varovani={len(prekryv)}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/nedostupnosti/{nedostupnost_id}/smazat")
def admin_nedostupnost_smazat(
    nedostupnost_id: int,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    _nedostupnost_nebo_404(conn, nedostupnost_id)
    repo.zrusit_nedostupnost(conn, nedostupnost_id)
    return RedirectResponse(url="/admin/nedostupnosti", status_code=status.HTTP_303_SEE_OTHER)


# --- úkol 5: admin - parametry pravidel (profily normalni/krizovy) ---

PROFILY = ("normalni", "krizovy")


def _validovat_nastaveni(n: NastaveniProfilu) -> str | None:
    """Kromě vnitřní konzistence (min<=max) i doménová minima z CLAUDE.md
    ("denní: 3-4 lidi, noční: tvrdě 1-2 - platí každý den, oba profily").
    Bez tohohle by šlo přes /admin/nastaveni tiše uložit profil, který
    tahle jinak neměnná pravidla poruší (viz audit) - solver.config.Config
    zná jen min<=max, ne konkrétní čísla, takže by to samo nechytilo."""
    if not (3 <= n.denni_min <= n.denni_max <= 4):
        return "Denní obsazení musí být v rozsahu 3-4 (min <= max), viz CLAUDE.md."
    if not (1 <= n.nocni_min <= n.nocni_max <= 2):
        return "Noční obsazení musí být v rozsahu 1-2 (min <= max), viz CLAUDE.md."
    if n.max_v_rade < 1:
        return "Max směn v řadě musí být alespoň 1."
    if n.max_smen_mesic < 1:
        return "Max směn/měsíc musí být alespoň 1."
    return None


@app.get("/admin/nastaveni")
def admin_nastaveni_formular(
    request: Request,
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    return sablony.TemplateResponse(
        request,
        "admin_nastaveni.html",
        {
            "uzivatel": uzivatel,
            "chyba": None,
            "nastaveni": {p: repo.nastaveni_pro_profil(conn, p) for p in PROFILY},
        },
    )


@app.post("/admin/nastaveni/{profil}")
def admin_nastaveni_ulozit(
    request: Request,
    profil: str,
    denni_min: int = Form(...),
    denni_max: int = Form(...),
    nocni_min: int = Form(...),
    nocni_max: int = Form(...),
    max_v_rade: int = Form(...),
    max_smen_mesic: int = Form(...),
    plne_obsazeni: int = Form(10),
    ferovost_nocni: int = Form(5),
    ferovost_vikendy: int = Form(3),
    ferovost_celkem: int = Form(4),
    nekompatibilni_penalizace: int = Form(8),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    if profil not in PROFILY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Neznámý profil")

    nastaveni = NastaveniProfilu(
        profil=profil, denni_min=denni_min, denni_max=denni_max, nocni_min=nocni_min,
        nocni_max=nocni_max, max_v_rade=max_v_rade, max_smen_mesic=max_smen_mesic,
        plne_obsazeni=plne_obsazeni, ferovost_nocni=ferovost_nocni,
        ferovost_vikendy=ferovost_vikendy, ferovost_celkem=ferovost_celkem,
        nekompatibilni_penalizace=nekompatibilni_penalizace,
    )
    chyba = _validovat_nastaveni(nastaveni)
    if chyba:
        vsechna_nastaveni = {p: repo.nastaveni_pro_profil(conn, p) for p in PROFILY}
        vsechna_nastaveni[profil] = nastaveni  # ukázat zpět rozepsané neplatné hodnoty
        return sablony.TemplateResponse(
            request,
            "admin_nastaveni.html",
            {"uzivatel": uzivatel, "chyba": chyba, "nastaveni": vsechna_nastaveni},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    repo.ulozit_nastaveni(conn, nastaveni)
    return RedirectResponse(url="/admin/nastaveni", status_code=status.HTTP_303_SEE_OTHER)
