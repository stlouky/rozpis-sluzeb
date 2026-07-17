"""Datové třídy odpovídající řádkům v db/schema.sql."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Zamestnanec:
    id: int
    jmeno: str
    aktivni_od: date
    aktivni_do: date | None
    stitky: str  # čárkou oddělené, prázdný řetězec = žádné
    max_smen_mesic: int | None = None  # None = společný strop z config.yaml

    @property
    def seznam_stitku(self) -> list[str]:
        return self.stitky.split(",") if self.stitky else []


@dataclass(frozen=True)
class Nedostupnost:
    id: int
    zamestnanec_id: int
    od: date
    do: date
    typ: str
    poznamka: str | None
    zakazana_smena: str | None = None  # None = celý den, jinak 'D'/'N'


@dataclass(frozen=True)
class Smena:
    id: int
    zamestnanec_id: int
    datum: date
    typ: str  # 'D' | 'N'
    locked: bool
    stav: str | None


@dataclass(frozen=True)
class Dvojice:
    id: int
    zamestnanec_a_id: int
    zamestnanec_b_id: int
    typ: str


@dataclass(frozen=True)
class Uzivatel:
    id: int
    jmeno: str
    heslo_hash: str
    role: str  # 'admin' | 'nahled'
