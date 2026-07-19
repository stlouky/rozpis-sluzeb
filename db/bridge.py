"""Most mezi DB a solverem: config_pro_mesic(conn, rok, mesic) -> Config.

Zaměstnanci, jejich nedostupnosti a nekompatibilní dvojice se berou ze
stavu DB. Obsazení, pravidla a váhy zatím zůstávají v config.yaml (fáze 2
je jen datová vrstva - správa vah/obsazení přes DB je otázka pro pozdější
fázi, až bude UI).
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import yaml

from solver.config import Config, config_from_dict
from solver.schedule import Schedule

from . import repository as repo

DEFAULT_CONFIG_YAML = Path(__file__).resolve().parent.parent / "config.yaml"


def dny_v_mesici(od: date, do: date, prvni_den: date, posledni_den: date) -> list[int]:
    """Ořízne interval [od, do] na rozsah měsíce [prvni_den, posledni_den]
    a vrátí seznam dní v měsíci (1-indexováno). Veřejné - sdílené i s
    web/mrizka.py (poznámky k nedostupnostem), ne jen s config_pro_mesic.
    """
    zacatek = max(od, prvni_den)
    konec = min(do, posledni_den)
    dny = []
    d = zacatek
    while d <= konec:
        dny.append(d.day)
        d += timedelta(days=1)
    return dny


def config_pro_mesic(
    conn: sqlite3.Connection,
    rok: int,
    mesic: int,
    config_yaml_cesta: str | Path = DEFAULT_CONFIG_YAML,
    profil: str = "normalni",
) -> Config:
    """Sestaví Config pro daný měsíc ze stavu DB + obsazení/pravidla/váhy.

    Obsazení/pravidla/váhy se berou z DB tabulky nastaveni pro daný
    profil ('normalni'/'krizovy'/'optimalizovany', viz db/schema.sql),
    pokud tam admin profil už uložil (úkol 5). Dokud neuložil, použije se
    config_yaml_cesta - tak zůstává config.yaml jediným zdrojem pro
    CLI/testy s fiktivními daty beze změny chování.
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])

    aktivni = repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    jmeno_podle_id = {z.id: z.jmeno for z in aktivni}

    zamestnanci_data = [
        {"jmeno": z.jmeno, "stitky": z.seznam_stitku} for z in aktivni
    ]
    max_smen_mesic_override = {
        z.jmeno: z.max_smen_mesic for z in aktivni if z.max_smen_mesic is not None
    }
    max_v_rade_override = {
        z.jmeno: z.max_za_sebou for z in aktivni if z.max_za_sebou is not None
    }

    nedostupnosti: dict[str, set[int]] = {}
    duvody_nedostupnosti: dict[str, dict[int, str]] = {}
    zakazane_smeny: dict[str, dict[int, tuple[str, ...]]] = {}

    # Trvalé osobní omezení typu směny (zamestnanec.zakaz_smeny) - na
    # rozdíl od nedostupnost.zakazana_smena (časově ohraničené) platí pro
    # VŠECHNY dny měsíce, proto se rovnou promítne do stejné zakazane_smeny
    # struktury, kterou solver už umí (žádná nová solver logika navíc).
    for z in aktivni:
        if z.zakaz_smeny is not None:
            dny_omezeni = zakazane_smeny.setdefault(z.jmeno, {})
            for den in range(1, posledni_den.day + 1):
                dny_omezeni[den] = dny_omezeni.get(den, ()) + (z.zakaz_smeny,)

    # N -> D zakázáno (CLAUDE.md) platí i přes hranici měsíce, ale solver
    # dny počítá jen 1..pocet_dni uvnitř JEDNOHO configu - bez tohohle by
    # noční směna z posledního dne PŘEDCHOZÍHO měsíce nebránila denní hned
    # 1. den tohohle měsíce (nález: Šestáková noční 31.7., navrhovaná
    # denní 1.8.). Kontroluje se přímo uložená směna (repo.smena_pro_den),
    # ne Config - carryover mezi měsíci žádný Config nezná.
    posledni_den_predchoziho_mesice = prvni_den - timedelta(days=1)
    predposledni_den_predchoziho_mesice = prvni_den - timedelta(days=2)
    for z in aktivni:
        predchozi_smena = repo.smena_pro_den(conn, z.id, posledni_den_predchoziho_mesice)
        if predchozi_smena is not None and predchozi_smena.typ == "N":
            dny_omezeni = zakazane_smeny.setdefault(z.jmeno, {})
            dny_omezeni[1] = dny_omezeni.get(1, ()) + ("D",)

            # 2 noční v řadě na konci předchozího měsíce (poslední den I
            # den před ním) -> povinné 2 dny volna hned na začátku tohohle
            # měsíce (max 2 noční v řadě, pak 2 dny volna - CLAUDE.md).
            # Nedostupnost (celý den), ne jen zakazane_smeny - tohle
            # zakazuje D i N, ne jen D.
            predposledni_smena = repo.smena_pro_den(
                conn, z.id, predposledni_den_predchoziho_mesice
            )
            if predposledni_smena is not None and predposledni_smena.typ == "N":
                nedostupnosti.setdefault(z.jmeno, set()).update({1, 2})
                duvody = duvody_nedostupnosti.setdefault(z.jmeno, {})
                duvody[1] = duvody.get(1, "POVINNE_VOLNO_PO_2_NOCNICH")
                duvody[2] = duvody.get(2, "POVINNE_VOLNO_PO_2_NOCNICH")

    # Nástup/odchod uprostřed měsíce: aktivni_zamestnanci_v_obdobi vrátí
    # zaměstnance, jehož aktivní interval se s měsícem JEN překrývá (viz
    # repository.py) - bez tohohle by zůstal solveru "dostupný" i po dnech,
    # kdy už fakticky není v pracovním poměru.
    vsechny_dny_mesice = set(range(1, posledni_den.day + 1))
    for z in aktivni:
        aktivni_dny = set(
            dny_v_mesici(z.aktivni_od, z.aktivni_do or posledni_den, prvni_den, posledni_den)
        )
        mimo_pomer = vsechny_dny_mesice - aktivni_dny
        if mimo_pomer:
            nedostupnosti.setdefault(z.jmeno, set()).update(mimo_pomer)
            duvody = duvody_nedostupnosti.setdefault(z.jmeno, {})
            for den in mimo_pomer:
                duvody[den] = "MIMO_POMER"

    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        if n.stav != "schvaleno":
            continue  # nepotvrzený/zamítnutý požadavek (úkol 9b) - do rozpisu se nepromítne
        jmeno = jmeno_podle_id.get(n.zamestnanec_id)
        if jmeno is None:
            continue  # zaměstnanec v tomto měsíci není aktivní
        dny = dny_v_mesici(n.od, n.do, prvni_den, posledni_den)
        if n.zakazana_smena is None:
            nedostupnosti.setdefault(jmeno, set()).update(dny)
            duvody = duvody_nedostupnosti.setdefault(jmeno, {})
            for den in dny:
                duvody[den] = n.typ
        else:
            dny_omezeni = zakazane_smeny.setdefault(jmeno, {})
            for den in dny:
                dny_omezeni[den] = dny_omezeni.get(den, ()) + (n.zakazana_smena,)

    # Zamčené směny jako pevný vstup solveru (úkol 9) - "přegenerovat
    # zbytek měsíce" je díky tomuhle jen normální config_pro_mesic +
    # generate_schedule, žádná zvláštní cesta navíc: solver dostane
    # minulost/zamčené jako HOTOVÝ fakt (viz Config.pevne_smeny) a sám z
    # něj těží pro N->D zákaz, max v řadě i fond.
    pevne_smeny: dict[str, dict[int, str]] = {}
    for s in repo.smeny_v_mesici(conn, rok, mesic):
        if not s.locked:
            continue
        jmeno = jmeno_podle_id.get(s.zamestnanec_id)
        if jmeno is None:
            continue
        pevne_smeny.setdefault(jmeno, {})[s.datum.day] = s.typ

    nekompatibilni_dvojice = []
    zakazane_dvojice = []
    for d in repo.dvojice_vsechny(conn):
        if d.zamestnanec_a_id not in jmeno_podle_id or d.zamestnanec_b_id not in jmeno_podle_id:
            continue
        par = [jmeno_podle_id[d.zamestnanec_a_id], jmeno_podle_id[d.zamestnanec_b_id]]
        if d.typ == "zakazano":
            zakazane_dvojice.append(par)
        else:
            nekompatibilni_dvojice.append(par)

    nastaveni = repo.nastaveni_pro_profil(conn, profil)
    if nastaveni is not None:
        obsazeni = {
            "denni_min": nastaveni.denni_min,
            "denni_max": nastaveni.denni_max,
            "nocni_min": nastaveni.nocni_min,
            "nocni_max": nastaveni.nocni_max,
        }
        pravidla = {"max_v_rade": nastaveni.max_v_rade, "max_smen_mesic": nastaveni.max_smen_mesic}
        vahy = {
            "plne_obsazeni": nastaveni.plne_obsazeni,
            "ferovost_nocni": nastaveni.ferovost_nocni,
            "ferovost_vikendy": nastaveni.ferovost_vikendy,
            "ferovost_celkem": nastaveni.ferovost_celkem,
            "nekompatibilni_penalizace": nastaveni.nekompatibilni_penalizace,
        }
    else:
        with open(config_yaml_cesta, encoding="utf-8") as f:
            vahy_config = yaml.safe_load(f)
        obsazeni = vahy_config["obsazeni"]
        pravidla = vahy_config["pravidla"]
        vahy = vahy_config.get("vahy", {})

    data = {
        "rok": rok,
        "mesic": mesic,
        "zamestnanci": zamestnanci_data,
        "obsazeni": obsazeni,
        "pravidla": pravidla,
        "nedostupnosti": {jmeno: sorted(dny) for jmeno, dny in nedostupnosti.items()},
        "nekompatibilni_dvojice": nekompatibilni_dvojice,
        "zakazane_dvojice": zakazane_dvojice,
        "vahy": vahy,
        "duvody_nedostupnosti": duvody_nedostupnosti,
        "zakazane_smeny": zakazane_smeny,
        "max_smen_mesic_override": max_smen_mesic_override,
        "max_v_rade_override": max_v_rade_override,
        "pevne_smeny": pevne_smeny,
    }
    return config_from_dict(data)


def souhrn_vstupu(conn: sqlite3.Connection, rok: int, mesic: int) -> tuple[int, int]:
    """(počet aktivních zaměstnanců, počet nedostupností) pro daný měsíc -
    rychlý přehled vstupu PŘED spuštěním solveru (viz db/cli.py generuj).

    config_pro_mesic ani generate_schedule nijak nekontrolují, jestli je
    vstup podezřele řídký - prázdná nedostupnost je pro solver validní
    stav (nikdo nemá nic nahlášeno), ne chyba, takže bez tohohle souhrnu
    není vidět, když někdo zapomene import-txt/zadání nedostupností
    spustit před generováním (viz incident: rozpis vznikl s nereálně
    volnou rukou, protože tabulka nedostupnost byla prázdná).
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])
    pocet_zamestnancu = len(repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den))
    pocet_nedostupnosti = len(repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den))
    return pocet_zamestnancu, pocet_nedostupnosti


def schvalit_nekonfliktni(
    conn: sqlite3.Connection, rok: int, mesic: int, profil: str = "normalni"
) -> list[int]:
    """Hromadně schválí všechny čekající (stav='podano') požadavky daného
    měsíce, které by neporušily orientační minimum (denni_min+nocni_min
    aktivního profilu) - úkol 9d, tlačítko "Schválit nekonfliktní" ve
    widgetu Správa požadavků. Je to heuristika (celodenní blokace vs.
    společný práh, ne skutečný běh solveru): schválení dne beze zbytku
    neznamená, že (pře)generování uspěje, jen že orientačně neklesne
    dostupnost pod práh. Konfliktní položky přeskočí, zůstanou 'podano'.

    Položky s zakazana_smena (částečný den, např. "zákaz nočních")
    celkovou dostupnost nesnižují - schválí se vždy bez kontroly.
    Vícedenní požadavek se schválí, jen když projde na VŠECH svých dnech.
    Vrátí seznam id schválených požadavků."""
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])
    nastaveni = repo.nastaveni_pro_profil(conn, profil)
    minimum = (nastaveni.denni_min + nastaveni.nocni_min) if nastaveni else 0
    celkem = len(repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den))

    vsechny = repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den)
    blokovano: dict[date, set[int]] = {}
    for n in vsechny:
        if n.stav != "schvaleno" or n.zakazana_smena is not None:
            continue
        for den in dny_v_mesici(n.od, n.do, prvni_den, posledni_den):
            blokovano.setdefault(date(rok, mesic, den), set()).add(n.zamestnanec_id)

    schvaleno_ids: list[int] = []
    for n in vsechny:
        if n.stav != "podano":
            continue
        if n.zakazana_smena is not None:
            repo.schvalit_pozadavek(conn, n.id)
            schvaleno_ids.append(n.id)
            continue

        dny = dny_v_mesici(n.od, n.do, prvni_den, posledni_den)
        neprosel = False
        for den in dny:
            datum = date(rok, mesic, den)
            blok = blokovano.get(datum, set())
            if n.zamestnanec_id in blok:
                continue  # už tak nedostupný jiným záznamem, schválení nic nezmění
            if celkem - len(blok) - 1 < minimum:
                neprosel = True
                break
        if neprosel:
            continue

        for den in dny:
            blokovano.setdefault(date(rok, mesic, den), set()).add(n.zamestnanec_id)
        repo.schvalit_pozadavek(conn, n.id)
        schvaleno_ids.append(n.id)

    return schvaleno_ids


def schedule_z_db(conn: sqlite3.Connection, rok: int, mesic: int) -> Schedule:
    """Sestaví Schedule (solver/schedule.py) z uložených směn v DB - pro
    zobrazení (web mřížka úkol 3, přepis do Cygnusu úkol 7), ať se
    obsazení/souhrn počítá stejnou logikou jako u PDF exportu
    (vystup/pdf.py), ne duplicitně.

    Na rozdíl od config_pro_mesic (DB -> vstup solveru) je tohle DB ->
    výstupní tvar solveru, čistě pro čtení uložených dat.
    """
    prvni_den = date(rok, mesic, 1)
    posledni_den = date(rok, mesic, calendar.monthrange(rok, mesic)[1])

    aktivni = repo.aktivni_zamestnanci_v_obdobi(conn, prvni_den, posledni_den)
    zamestnanec_podle_id = {z.id: z for z in aktivni}
    jmeno_podle_id = {z.id: z.jmeno for z in aktivni}
    jmena = tuple(jmeno_podle_id.values())

    smeny: dict[tuple[str, int], str] = {}
    zamcene: set[tuple[str, int]] = set()
    for s in repo.smeny_v_mesici(conn, rok, mesic):
        jmeno = jmeno_podle_id.get(s.zamestnanec_id)
        if jmeno is None:
            continue  # zaměstnanec mimo aktivní rozsah měsíce (viz níž)
        smeny[(jmeno, s.datum.day)] = s.typ
        if s.locked:
            zamcene.add((jmeno, s.datum.day))

    duvody_nedostupnosti: dict[tuple[str, int], str] = {}
    for n in repo.nedostupnosti_v_obdobi(conn, prvni_den, posledni_den):
        z = zamestnanec_podle_id.get(n.zamestnanec_id)
        if z is None:
            continue
        # Nedostupnost oříznout na aktivní rozsah zaměstnance - starý
        # záznam (např. "ne noční směnu" na celý měsíc, zadaný dřív, než
        # bylo jasné, že brigáda/poměr uprostřed měsíce skončí) nesmí
        # "svítit" v mřížce ještě po dnech, kdy už zaměstnanec fakticky
        # neexistuje (viz nález: prázdné buňky po konci poměru zůstaly
        # popsané starým důvodem, místo aby byly prázdné).
        od_orez = max(n.od, z.aktivni_od)
        do_orez = min(n.do, z.aktivni_do or posledni_den)
        if od_orez > do_orez:
            continue
        for den in dny_v_mesici(od_orez, do_orez, prvni_den, posledni_den):
            duvody_nedostupnosti.setdefault((jmeno_podle_id[n.zamestnanec_id], den), n.typ)

    return Schedule(
        rok=rok,
        mesic=mesic,
        jmena=jmena,
        smeny=smeny,
        status="ULOZENO",
        cas_reseni=0.0,
        duvody_nedostupnosti=duvody_nedostupnosti,
        zamcene=frozenset(zamcene),
    )
