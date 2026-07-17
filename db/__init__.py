"""Datová vrstva nad SQLite (fáze 2) - repository pattern, čisté sqlite3."""

from .bridge import config_pro_mesic
from .models import Dvojice, Nedostupnost, Uzivatel, Zamestnanec
from .repository import (
    aktivni_zamestnanci,
    aktivni_zamestnanci_v_obdobi,
    deaktivovat_zamestnance,
    dvojice_vsechny,
    inicializovat_schema,
    nedostupnosti_v_obdobi,
    opravit_jmeno_zamestnance,
    pridat_dvojici,
    pridat_nedostupnost,
    pridat_zamestnance,
    pripojit,
    pripojit_a_inicializovat,
    uzivatel_podle_id,
    uzivatel_podle_jmena,
    vytvorit_uzivatele,
    zmenit_heslo,
    zrusit_nedostupnost,
)

__all__ = [
    "config_pro_mesic",
    "Zamestnanec",
    "Nedostupnost",
    "Dvojice",
    "Uzivatel",
    "pripojit",
    "pripojit_a_inicializovat",
    "inicializovat_schema",
    "pridat_zamestnance",
    "deaktivovat_zamestnance",
    "opravit_jmeno_zamestnance",
    "aktivni_zamestnanci",
    "aktivni_zamestnanci_v_obdobi",
    "pridat_nedostupnost",
    "zrusit_nedostupnost",
    "nedostupnosti_v_obdobi",
    "pridat_dvojici",
    "dvojice_vsechny",
    "vytvorit_uzivatele",
    "uzivatel_podle_jmena",
    "uzivatel_podle_id",
    "zmenit_heslo",
]
