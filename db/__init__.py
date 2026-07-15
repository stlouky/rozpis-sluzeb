"""Datová vrstva nad SQLite (fáze 2) - repository pattern, čisté sqlite3."""

from .bridge import config_pro_mesic
from .models import Dvojice, Nedostupnost, Zamestnanec
from .repository import (
    aktivni_zamestnanci,
    aktivni_zamestnanci_v_obdobi,
    deaktivovat_zamestnance,
    dvojice_vsechny,
    inicializovat_schema,
    nedostupnosti_v_obdobi,
    pridat_dvojici,
    pridat_nedostupnost,
    pridat_zamestnance,
    pripojit,
    zrusit_nedostupnost,
)

__all__ = [
    "config_pro_mesic",
    "Zamestnanec",
    "Nedostupnost",
    "Dvojice",
    "pripojit",
    "inicializovat_schema",
    "pridat_zamestnance",
    "deaktivovat_zamestnance",
    "aktivni_zamestnanci",
    "aktivni_zamestnanci_v_obdobi",
    "pridat_nedostupnost",
    "zrusit_nedostupnost",
    "nedostupnosti_v_obdobi",
    "pridat_dvojici",
    "dvojice_vsechny",
]
