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
    zakaz_smeny: str | None = None  # 'D' | 'N' | None - trvalý zákaz typu směny
    max_za_sebou: int | None = None  # None = společné pravidla.max_v_rade

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
class PreskocenaSmena:
    """Záznam o konfliktu při ulozit_rozpis(): pro (zamestnanec_id, datum)
    už existovala zamčená směna, takže nový typ z rozpisu se zahodil -
    zamčená vždy vyhrává (viz db/repository.py)."""

    zamestnanec_id: int
    jmeno: str
    datum: date
    puvodni_typ: str  # co zůstalo (zamčená směna)
    novy_typ: str  # co rozpis navrhoval a co se zahodilo


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


@dataclass(frozen=True)
class NastaveniProfilu:
    """Parametry pravidel pro jeden pojmenovaný profil ('normalni' /
    'krizovy' / 'optimalizovany', viz db/schema.sql) - obsazení,
    max_v_rade, max_smen_mesic a váhy pohromadě, ve stejném tvaru, jaký
    solver.config.config_from_dict čeká pod klíči obsazeni/pravidla/vahy."""

    profil: str
    denni_min: int
    denni_max: int
    nocni_min: int
    nocni_max: int
    max_v_rade: int
    max_smen_mesic: int
    plne_obsazeni: int = 10
    ferovost_nocni: int = 5
    ferovost_vikendy: int = 3
    ferovost_celkem: int = 4
    nekompatibilni_penalizace: int = 8
