"""FastAPI aplikace - kostra webu + přihlášení (úkol 1).

Server-side rendering přes Jinja2, žádné SPA (viz CLAUDE.md). Mřížka
rozpisu, správa zaměstnanců a další funkčnost přibudou v dalších úkolech
(zadani-faze3-web.md) - tady je jen kostra a login/logout.
"""

from __future__ import annotations

import dataclasses
import json
import os
import secrets
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from db import repository as repo
from db.bridge import config_pro_mesic, schedule_z_db, schvalit_nekonfliktni
from db.cesta import vychozi_cesta_db
from db.models import NastaveniProfilu, Nedostupnost, Uzivatel, Zamestnanec
from solver.core import NelzeSestavitError, generate_schedule
from vystup.pdf import vygenerovat_pdf

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
from .diff import sestavit_diff
from .mrizka import (
    NAZEV_NEDOSTUPNOSTI,
    TYPY_NEDOSTUPNOSTI_V_CYKLU,
    sestavit_mrizku,
    sestavit_pozadavky_widget,
)
from .prepis import sestavit_prepis

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


def _sousedni_mesice(rok: int, mes: int) -> tuple[str, str]:
    predchozi_rok, predchozi_mes = (rok - 1, 12) if mes == 1 else (rok, mes - 1)
    dalsi_rok, dalsi_mes = (rok + 1, 1) if mes == 12 else (rok, mes + 1)
    return f"{predchozi_rok}-{predchozi_mes:02d}", f"{dalsi_rok}-{dalsi_mes:02d}"


def _bezpecny_json(data) -> str:
    """json.dumps s escapovaným '</' - vkládá se přímo do <script> tagu
    (viz mrizka.html), kde by řetězec '</script>' v datech (jméno/popis)
    jinak mohl tag předčasně ukončit."""
    return json.dumps(data).replace("</", "<\\/")


def _bezpecny_navrat(navrat: str, vychozi: str) -> str:
    """Widgety požadavků (úkol 9d) žijí na /rozpis, ale POST routy pro
    podání/schválení/zamítnutí zůstávají sdílené s /pozadavky - navrat
    říká, kam se vrátit po odeslání. Jen relativní cesta v appce (žádné
    "//" - protokol-relativní adresa by mohla vést mimo appku), jinak
    vychozi."""
    if navrat.startswith("/") and not navrat.startswith("//"):
        return navrat
    return vychozi


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
    predchozi_mesic, dalsi_mesic = _sousedni_mesice(rok, mes)
    mesic_str = f"{rok}-{mes:02d}"
    dny_pozadavku = sestavit_pozadavky_widget(conn, rok, mes)
    kontext = {
        "uzivatel": uzivatel,
        "je_admin": je_admin,
        "mrizka": mrizka,
        "predchozi_mesic": predchozi_mesic,
        "dalsi_mesic": dalsi_mesic,
        "vygenerovano": False,
        "generovani_status": None,
        "generovani_cas": None,
        "preskoceno": 0,
        "chyba_generovani": None,
        "profil_generovani": None,
        "profil_generovani_nazev": None,
        "ma_zamcene_smeny": False,
        "beze_zmeny": False,
        "hodnoty_bunky": HODNOTY_BUNKY,
        # --- úkol 9d: kalendářové widgety požadavků pod mřížkou ---
        "mesic_str": mesic_str,
        "pozadavky_widget_json": _bezpecny_json([dataclasses.asdict(d) for d in dny_pozadavku]),
        "pozadavky_zamestnanci": repo.aktivni_zamestnanci(conn, date.today()),
        "pozadavky_typy": NAZEV_NEDOSTUPNOSTI,
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
    beze_zmeny: bool = False,
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    je_admin = uzivatel.role == "admin"
    rok, mes = _rozlozit_mesic(mesic)

    return _vykreslit_rozpis(
        request, conn, uzivatel, rok, mes, je_admin,
        vygenerovano=vygenerovano,
        generovani_status=generovani_status,
        generovani_cas=generovani_cas,
        preskoceno=preskoceno,
        beze_zmeny=beze_zmeny,
    )


# --- úkol 6+9: admin - VYGENEROVAT (+ zamykání, diff, přegenerování zbytku) ---

GENEROVANI_TIME_LIMIT_S = 30.0
# Pevný seed vynucuje num_search_workers=1 (viz solver/core.py) - server
# sdílí 2 vCPU s rbscannerem, úloha je malá, takže rychlost neutrpí; vedlejší
# efekt je deterministický výsledek, stejně jako v testech (viz zadani-faze3-web.md).
GENEROVANI_SEED = 42

PROFILY_NAZVY = {"normalni": "normální", "krizovy": "krizový", "optimalizovany": "optimalizovaný"}


def _vyresit(conn: sqlite3.Connection, rok: int, mes: int, profil: str):
    """Sestaví config (zamčené směny jako pevný vstup, viz
    db.bridge.config_pro_mesic) a zavolá solver. Nic neukládá - jen
    vrátí Config a Schedule, ať to může sdílet POST /rozpis/generovat
    (náhled diffu) i POST /rozpis/generovat/potvrdit (skutečné uložení,
    znovu vyřeší se stejným seedem -> stejný výsledek, viz úkol 6)."""
    config = config_pro_mesic(conn, rok, mes, profil=profil)
    schedule = generate_schedule(
        config, time_limit_s=GENEROVANI_TIME_LIMIT_S, random_seed=GENEROVANI_SEED,
        prioritizovat_obsazeni=(profil == "optimalizovany"),
    )
    return config, schedule


@app.post("/rozpis/generovat")
def rozpis_generovat(
    request: Request,
    mesic: str = Form(...),
    profil: str = Form("normalni"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    rok, mes = _rozlozit_mesic(mesic)
    # "Zamknout minulost a odpracované směny, přegenerovat jen zbytek
    # měsíce" (CLAUDE.md klíčové workflow) - není samostatná akce, děje
    # se to automaticky před každým (pře)generováním. Config pak zamčené
    # (vč. právě zamčené minulosti) bere jako pevný vstup solveru (viz
    # db.bridge.config_pro_mesic), takže "vygenerovat" a "přegenerovat
    # zbytek" jsou ve skutečnosti stejná operace.
    repo.zamknout_minulost(conn, rok, mes)

    try:
        config, schedule = _vyresit(conn, rok, mes, profil)
    except NelzeSestavitError as e:
        # Nesplnitelnost se ukáže rovnou na mřížce (ne HTTP 500) - viz
        # solver.core._diagnostikuj_nesplnitelnost pro obsah e.duvody.
        # ma_zamcene_smeny řídí, jestli má smysl nabídnout "odemknout
        # budoucí zamčené směny a zkusit znovu" (úkol 9) - bez zamčené
        # směny v měsíci by to tlačítko nemělo co dělat.
        config_bez_reseni = config_pro_mesic(conn, rok, mes, profil=profil)
        return _vykreslit_rozpis(
            request, conn, uzivatel, rok, mes, je_admin=True,
            chyba_generovani=e.duvody,
            profil_generovani=profil,
            profil_generovani_nazev=PROFILY_NAZVY.get(profil, profil),
            ma_zamcene_smeny=bool(config_bez_reseni.pevne_smeny),
        )

    puvodni = schedule_z_db(conn, rok, mes)
    diff = sestavit_diff(puvodni, schedule)

    if not diff:
        # Nic se nezměnilo - uložit je formalita (zamčené i tak zůstávají
        # netknuté), ale nemá smysl ptát se na potvrzení prázdného diffu.
        preskocene = repo.ulozit_rozpis(conn, schedule)
        url = (
            f"/rozpis?mesic={rok}-{mes:02d}&vygenerovano=1"
            f"&generovani_status={schedule.status}&generovani_cas={schedule.cas_reseni:.1f}"
            f"&preskoceno={len(preskocene)}&beze_zmeny=1"
        )
        return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    return sablony.TemplateResponse(
        request,
        "generovani_diff.html",
        {
            "uzivatel": uzivatel,
            "rok": rok,
            "mesic": mes,
            "profil": profil,
            "diff": diff,
            "status_reseni": schedule.status,
            "cas_reseni": schedule.cas_reseni,
        },
    )


@app.post("/rozpis/generovat/potvrdit")
def rozpis_generovat_potvrdit(
    mesic: str = Form(...),
    profil: str = Form("normalni"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    """Skutečné uložení po náhledu diffu - znovu vyřeší (stejný config +
    stejný pevný seed = stejný výsledek, viz _vyresit) a teprve teď
    zavolá ulozit_rozpis. Mezi náhledem a potvrzením se stav DB
    (v praxi) nemění - appka je jednouživatelská admin session - ale
    kdyby se přesto stalo, že mezitím přibylo něco, co dělá zadání
    nesplnitelným, radši tichý návrat na mřížku než 500."""
    rok, mes = _rozlozit_mesic(mesic)
    try:
        _, schedule = _vyresit(conn, rok, mes, profil)
    except NelzeSestavitError:
        return RedirectResponse(
            url=f"/rozpis?mesic={rok}-{mes:02d}", status_code=status.HTTP_303_SEE_OTHER
        )

    preskocene = repo.ulozit_rozpis(conn, schedule)
    url = (
        f"/rozpis?mesic={rok}-{mes:02d}&vygenerovano=1"
        f"&generovani_status={schedule.status}&generovani_cas={schedule.cas_reseni:.1f}"
        f"&preskoceno={len(preskocene)}"
    )
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/rozpis/generovat/odemknout-a-zkusit")
def rozpis_generovat_odemknout_a_zkusit(
    request: Request,
    mesic: str = Form(...),
    profil: str = Form("normalni"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    """"Odemknout konfliktní směny" (úkol 9 zadání) - přesně určit,
    KTERÁ zamčená směna je za nesplnitelností, by vyžadovalo postupně
    zkoušet kombinace (drahé, mimo rozsah úkolu). Pragmatická náhrada:
    odemkne VŠECHNY budoucí (datum > dnes) zamčené směny v měsíci -
    zamčená minulost (datum <= dnes) zůstává nedotčená - a zkusí to
    znovu."""
    rok, mes = _rozlozit_mesic(mesic)
    dnes = date.today()
    budouci_zamcene = [
        s.id for s in repo.smeny_v_mesici(conn, rok, mes) if s.locked and s.datum > dnes
    ]
    repo.odemknout_smeny(conn, budouci_zamcene)
    return rozpis_generovat(request, mesic, profil, uzivatel, conn)


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
    try:
        novy_id = repo.pridat_zamestnance(conn, jmeno.strip(), aktivni_od, stitky, strop)
    except ValueError as e:
        return sablony.TemplateResponse(
            request,
            "admin_zamestnanec_novy.html",
            {
                "uzivatel": uzivatel,
                "chyba": str(e),
                "dnes": date.today().isoformat(),
                "mozni_partneri": repo.aktivni_zamestnanci(conn, date.today()),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    # Formulář nabízí jen aktivní zaměstnance jako partnery (viz GET výš),
    # ale mezi zobrazením a odesláním formuláře mohl partner zmizet
    # (smazání) - tiché přeskočení neplatného id, ať se to nezhroutí na
    # syrový sqlite3.IntegrityError (cizí klíč, viz audit).
    znama_id = {z.id for z in repo.vsichni_zamestnanci(conn)}
    for partner_id in dvojice_s:
        if partner_id in znama_id:
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
    request: Request,
    zamestnanec_id: int,
    jmeno: str = Form(...),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    zamestnanec = _zamestnanec_nebo_404(conn, zamestnanec_id)
    if jmeno.strip():
        try:
            repo.opravit_jmeno_zamestnance(conn, zamestnanec_id, jmeno.strip())
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
    _zamestnanec_nebo_404(conn, zamestnanec_id)
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


# --- úkol 9b: samoobslužné podávání požadavků (obě role) ---
# Typ POZADAVEK existoval v datech od začátku (zadávaný admin/CLI cestou
# rovnou jako 'schvaleno') - tady dostává vlastní stránku a schvalovací
# workflow, ať to nemusí chodit přes admina/CLI. Systém neřeší, KDO
# požadavek podal (sdílený nahled/host účet nemá per-osobu identitu) -
# jen PRO KOHO je určen (výběr zaměstnance ve formuláři).

NAZEV_STAVU_POZADAVKU = {
    "podano": "Čeká na schválení",
    "schvaleno": "Schváleno",
    "zamitnuto": "Zamítnuto",
}


@app.get("/pozadavky")
def pozadavky_seznam(
    request: Request,
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    jmeno_podle_id = {z.id: z.jmeno for z in repo.vsichni_zamestnanci(conn)}
    return sablony.TemplateResponse(
        request,
        "pozadavky.html",
        {
            "uzivatel": uzivatel,
            "je_admin": uzivatel.role == "admin",
            # úkol 9d: žádný typový filtr - stránka ukazuje obsazenost
            # napříč všemi typy, ne jen samoobslužný POZADAVEK.
            "pozadavky": repo.vsechny_nedostupnosti(conn),
            "jmeno_podle_id": jmeno_podle_id,
            "nazvy_stavu": NAZEV_STAVU_POZADAVKU,
        },
    )


@app.get("/pozadavky/novy")
def pozadavek_novy_formular(
    request: Request,
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    return sablony.TemplateResponse(
        request,
        "pozadavek_novy.html",
        {
            "uzivatel": uzivatel,
            "chyba": None,
            "zamestnanci": repo.aktivni_zamestnanci(conn, date.today()),
            "typy": NAZEV_NEDOSTUPNOSTI,
        },
    )


@app.post("/pozadavky")
def pozadavek_novy_odeslani(
    request: Request,
    zamestnanec_id: int = Form(...),
    od: date = Form(...),
    do: date = Form(...),
    typ: str = Form("POZADAVEK"),
    popis: str = Form(""),
    navrat: str = Form("/pozadavky"),
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    cil = _bezpecny_navrat(navrat, "/pozadavky")
    _zamestnanec_nebo_404(conn, zamestnanec_id)
    try:
        repo.pridat_pozadavek(conn, zamestnanec_id, od, do, popis.strip() or None, typ=typ)
    except ValueError as e:
        return sablony.TemplateResponse(
            request,
            "pozadavek_novy.html",
            {
                "uzivatel": uzivatel,
                "chyba": str(e),
                "zamestnanci": repo.aktivni_zamestnanci(conn, date.today()),
                "typy": NAZEV_NEDOSTUPNOSTI,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(url=cil, status_code=status.HTTP_303_SEE_OTHER)


def _pozadavek_nebo_404(conn: sqlite3.Connection, pozadavek_id: int) -> Nedostupnost:
    """Schválit/zamítnout smí jen položku, co na to čeká - stav='podano'
    (úkol 9d: dřív gatovalo typ POZADAVEK, ale self-service teď zakládá
    i skutečné typy DOV/NEM/... - rozhoduje stav, ne typ). 'podano' navíc
    ze své podstaty může vzniknout jen přes self-service (admin/CLI cesta
    zapisuje rovnou 'schvaleno'), takže tahle kontrola sama o sobě chrání
    před tím, aby se přes tuhle routu sáhlo na běžný admin záznam."""
    pozadavek = repo.nedostupnost_podle_id(conn, pozadavek_id)
    if pozadavek is None or pozadavek.stav != "podano":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Požadavek neexistuje")
    return pozadavek


@app.post("/pozadavky/{pozadavek_id}/schvalit")
def pozadavek_schvalit(
    pozadavek_id: int,
    navrat: str = Form("/pozadavky"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    _pozadavek_nebo_404(conn, pozadavek_id)
    repo.schvalit_pozadavek(conn, pozadavek_id)
    return RedirectResponse(
        url=_bezpecny_navrat(navrat, "/pozadavky"), status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/pozadavky/{pozadavek_id}/zamitnout")
def pozadavek_zamitnout(
    pozadavek_id: int,
    navrat: str = Form("/pozadavky"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    _pozadavek_nebo_404(conn, pozadavek_id)
    repo.zamitnout_pozadavek(conn, pozadavek_id)
    return RedirectResponse(
        url=_bezpecny_navrat(navrat, "/pozadavky"), status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/rozpis/pozadavky/schvalit-nekonfliktni")
def rozpis_pozadavky_schvalit_nekonfliktni(
    mesic: str = Form(...),
    profil: str = Form("normalni"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    """Tlačítko "Schválit nekonfliktní" ve widgetu Správa požadavků
    (úkol 9d) - viz db.bridge.schvalit_nekonfliktni pro samotnou
    heuristiku (jen orientační, ne záruka proveditelnosti)."""
    rok, mes = _rozlozit_mesic(mesic)
    schvalit_nekonfliktni(conn, rok, mes, profil=profil)
    return RedirectResponse(url=f"/rozpis?mesic={mesic}", status_code=status.HTTP_303_SEE_OTHER)


# --- úkol 5: admin - parametry pravidel (profily normalni/krizovy) ---
# + úkol 9c (na přání, upřesněno): "optimalizovany" - stejná tvrdá
# pravidla i výchozí váhy jako normalni, ale priorita je CO NEJMÉNĚ
# krizových dnů (dnů pod plným obsazením), teprve pak férovost.
# Zkoušelo se nejdřív jen vysoká vahy.plne_obsazeni (matematicky by
# měla dominovat) - reálně to ale ZHORŠILO výsledek (10 → 19 krizových
# dnů na reálných datech), protože velký koeficient v jediném součtu
# mate CP-SAT search heuristiky. Skutečná priorita je zajištěná
# strukturálně: `_vyresit` níž volá solver s `prioritizovat_obsazeni=
# True` pro tenhle profil (dvoufázové řešení - viz
# solver/core.py:generate_schedule), ne velikostí vah - ty tak můžou
# zůstat stejné jako u normalni (jen tiebreak/férovost mezi řešeními se
# stejným nejlepším obsazením).

PROFILY = ("normalni", "krizovy", "optimalizovany")


def _validovat_nastaveni(n: NastaveniProfilu) -> str | None:
    """Kromě vnitřní konzistence (min<=max) i doménová minima z CLAUDE.md
    ("denní: 3-4 lidi, noční: tvrdě 1-2 - platí každý den, všechny profily").
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


# --- úkol 7: pohled pro přepis do Cygnusu ---

@app.get("/rozpis/prepis")
def rozpis_prepis(
    request: Request,
    mesic: str | None = None,
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    je_admin = uzivatel.role == "admin"
    rok, mes = _rozlozit_mesic(mesic)
    prepis = sestavit_prepis(conn, rok, mes)
    predchozi_mesic, dalsi_mesic = _sousedni_mesice(rok, mes)

    return sablony.TemplateResponse(
        request,
        "prepis.html",
        {
            "uzivatel": uzivatel,
            "je_admin": je_admin,
            "prepis": prepis,
            "predchozi_mesic": predchozi_mesic,
            "dalsi_mesic": dalsi_mesic,
        },
    )


@app.get("/rozpis/pdf")
def rozpis_pdf(
    mesic: str | None = None,
    uzivatel: Uzivatel = Depends(vyzadovat_prihlaseni),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    """PDF na nástěnku - existující vystup.pdf.vygenerovat_pdf, jen route
    + stažení (viz úkol 7 zadání - export je hotový, nic se tu znovu
    neimplementuje). Zapisuje se do dočasného souboru, ať se
    vygenerovat_pdf nemusí měnit - smaže se hned po odeslání odpovědi."""
    je_admin = uzivatel.role == "admin"
    rok, mes = _rozlozit_mesic(mesic)
    schedule = schedule_z_db(conn, rok, mes)

    fd, cesta = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        vygenerovat_pdf(schedule, cesta)
    except Exception:
        # Bez tohohle by při chybě uvnitř vygenerovat_pdf (viz audit)
        # dočasný soubor zůstal v /tmp navždy - BackgroundTask níž se
        # zaregistruje, jen když FileResponse vůbec vznikne.
        os.unlink(cesta)
        raise

    return FileResponse(
        cesta,
        media_type="application/pdf",
        filename=f"rozpis-{rok}-{mes:02d}.pdf",
        background=BackgroundTask(os.unlink, cesta),
    )


# --- úkol 8+9: admin - ruční úprava buňky + přegenerování zbytku od úpravy ---

# Buňka cykluje mezi směnou (D/N), volnem a jednodenní nedostupností
# (DOV/OST/NEM) - víc typů/vícedenní záznamy zůstávají jen na
# /admin/nedostupnosti (viz web/mrizka.py:TYPY_NEDOSTUPNOSTI_V_CYKLU).
HODNOTY_BUNKY = ("D", "N", "") + TYPY_NEDOSTUPNOSTI_V_CYKLU


def _nastavit_hodnotu_bunky(
    conn: sqlite3.Connection, zamestnanec_id: int, datum: date, hodnota: str
) -> str | None:
    """Nastaví ruční hodnotu buňky - směna a jednodenní nedostupnost se
    vzájemně vylučují, takže se vždy jedna nastaví a druhá smaže. Vrátí
    chybovou hlášku (str) při neúspěchu (zamčená směna/vícedenní
    nedostupnost), jinak None.

    Obě podmínky se ověří PŘED jakýmkoli zápisem - repo.nastavit_smenu i
    repo.nastavit_nedostupnost_jednoho_dne commitují každá samostatně, takže
    volání obou za sebou v try/except by při chybě DRUHÉHO volání nechalo v
    DB nekonzistentní částečný zápis z prvního (nález auditu appky: klik na
    "D" u dne, který je součástí vícedenní DOV, dřív nejdřív zapsal a
    commitnul směnu D a AŽ POTOM spadl na ValueError kvůli nedostupnosti -
    směna D zůstala v DB uložená vedle dovolené, aniž by se to projevilo
    jako chyba)."""
    typ_smeny = hodnota if hodnota in ("D", "N") else None
    typ_nedostupnosti = hodnota if hodnota in TYPY_NEDOSTUPNOSTI_V_CYKLU else None

    existujici_smena = repo.smena_pro_den(conn, zamestnanec_id, datum)
    if existujici_smena is not None and existujici_smena.locked:
        return f"Směna {datum.isoformat()} je zamčená, nejde ji ručně upravit - nejdřív odemkni."

    existujici_nedostupnost = repo.nedostupnost_pro_den(conn, zamestnanec_id, datum)
    if existujici_nedostupnost is not None and existujici_nedostupnost.od != existujici_nedostupnost.do:
        return (
            f"Nedostupnost {existujici_nedostupnost.od.isoformat()}"
            f"–{existujici_nedostupnost.do.isoformat()} je vícedenní, nejde upravit "
            f"po jednom dni - uprav ji na /admin/nedostupnosti."
        )

    repo.nastavit_smenu(conn, zamestnanec_id, datum, typ_smeny)
    repo.nastavit_nedostupnost_jednoho_dne(conn, zamestnanec_id, datum, typ_nedostupnosti)
    return None


@app.post("/rozpis/bunka/{zamestnanec_id}/{datum}")
def rozpis_bunka_upravit(
    request: Request,
    zamestnanec_id: int,
    datum: date,
    mesic: str = Form(...),
    hodnota: str = Form(""),
    profil: str = Form("normalni"),
    uzivatel: Uzivatel = Depends(vyzadovat_admina),
    conn: sqlite3.Connection = Depends(ziskat_pripojeni),
):
    """Ruční úprava jedné buňky (klik cykluje hodnotu na frontendu,
    Enter odešle - viz mrizka.html) rovnou spustí přegenerování zbytku
    měsíce (úkol 9 - na přání, ne diff/potvrzení jako hlavní tlačítko
    "Vygenerovat": tahle akce uživatel už jednou potvrdil tím, že ručně
    vybral hodnotu).

    Na přání NENÍ ruční úprava trvalý zámek: je to jednorázová korekce,
    ne požadavek. Zvolená D/N směna se zamkne JEN na dobu tohoto jednoho
    přepočtu (aby ji přegenerování hned nepřepsalo něčím jiným) a hned
    po dopočtu se zase odemkne - takže příští "Vygenerovat rozpis" i
    další ruční úprava s ní může znovu volně hýbat, omyl jde vzít zpět.
    Trvale se zamyká jen skutečná minulost (zamknout_minulost), stejně
    jako u hlavního tlačítka. Ostatní lidi ve stejný den zůstávají volní
    proměnní, aby je solver mohl doplnit/přeskupit (např. při odebrání
    někoho ze směny má šanci najít náhradu - viz audit)."""
    _zamestnanec_nebo_404(conn, zamestnanec_id)
    rok, mes = _rozlozit_mesic(mesic)

    chyba = _nastavit_hodnotu_bunky(conn, zamestnanec_id, datum, hodnota)
    if chyba:
        # Zamčená směna/vícedenní nedostupnost - šablona takovou buňku
        # vůbec nedělá klikatelnou (viz mrizka.html), tenhle požadavek
        # jde jen ručně sestavený. Tiše návrat, stav v DB je platný.
        return RedirectResponse(url=f"/rozpis?mesic={mesic}", status_code=status.HTTP_303_SEE_OTHER)

    repo.zamknout_minulost(conn, rok, mes)

    docasne_zamcena_id: int | None = None
    if hodnota in ("D", "N"):
        smena = repo.smena_pro_den(conn, zamestnanec_id, datum)
        if smena is not None and not smena.locked:
            repo.zamknout_smeny(conn, [smena.id])
            docasne_zamcena_id = smena.id

    try:
        config, schedule = _vyresit(conn, rok, mes, profil)
    except NelzeSestavitError as e:
        if docasne_zamcena_id is not None:
            repo.odemknout_smeny(conn, [docasne_zamcena_id])
        config_bez_reseni = config_pro_mesic(conn, rok, mes, profil=profil)
        return _vykreslit_rozpis(
            request, conn, uzivatel, rok, mes, je_admin=True,
            chyba_generovani=e.duvody,
            profil_generovani=profil,
            profil_generovani_nazev=PROFILY_NAZVY.get(profil, profil),
            ma_zamcene_smeny=bool(config_bez_reseni.pevne_smeny),
        )

    if docasne_zamcena_id is not None:
        repo.odemknout_smeny(conn, [docasne_zamcena_id])

    preskocene = repo.ulozit_rozpis(conn, schedule)
    url = (
        f"/rozpis?mesic={rok}-{mes:02d}&vygenerovano=1"
        f"&generovani_status={schedule.status}&generovani_cas={schedule.cas_reseni:.1f}"
        f"&preskoceno={len(preskocene)}"
    )
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
