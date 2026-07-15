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


@dataclass(frozen=True)
class Dvojice:
    id: int
    zamestnanec_a_id: int
    zamestnanec_b_id: int
    typ: str
