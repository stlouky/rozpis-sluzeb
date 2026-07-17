"""Jednotná výchozí cesta k SQLite databázi.

Sdíleno mezi CLI (db/cli.py) a webem (web/app.py) - dřív měl každý svou
nezávislou definici a rozjely se na dva různé soubory: CLI zapisovalo do
data/rozpis.db, web se připojoval na starý rozpis.db v rootu (bez tabulky
uzivatel, protože vznikl ještě před úkolem 1) a hlásil "no such table:
uzivatel". Teď existuje jen JEDNO místo, kde se výchozí cesta počítá.
"""

from __future__ import annotations

import os
from pathlib import Path

KOREN_REPO = Path(__file__).resolve().parent.parent


def vychozi_cesta_db() -> Path:
    """ROZPIS_DB env (produkce, viz DEPLOY.md/zadani-faze3-web.md úkol 10),
    jinak <repo>/data/rozpis.db. Volá se čerstvě při každém použití (ne
    jednou při importu modulu), ať jde v testech přepnout přes
    monkeypatch.setenv bez nutnosti reloadovat moduly.
    """
    return Path(os.environ.get("ROZPIS_DB", str(KOREN_REPO / "data" / "rozpis.db")))
