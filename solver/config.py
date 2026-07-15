"""Konfigurace solveru: dataclassy + načtení z YAML.

Ve fázi 2 tahle data ponesou SQLite tabulky (employee, unavailability,
pair_rule, settings) podle NAVRH.md — tenhle modul je zatím jediný
zdroj pravdy a jeho tvar je s tím záměrně zarovnaný.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Neplatná nebo nekonzistentní konfigurace."""


@dataclass(frozen=True)
class Employee:
    jmeno: str
    stitky: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Obsazeni:
    denni_min: int
    denni_max: int
    nocni_min: int
    nocni_max: int


@dataclass(frozen=True)
class Pravidla:
    max_v_rade: int
    max_smen_mesic: int


@dataclass(frozen=True)
class Vahy:
    plne_obsazeni: int = 10
    ferovost_nocni: int = 5
    ferovost_vikendy: int = 3
    ferovost_celkem: int = 4
    nekompatibilni_penalizace: int = 8


@dataclass(frozen=True)
class Config:
    rok: int
    mesic: int
    zamestnanci: tuple[Employee, ...]
    obsazeni: Obsazeni
    pravidla: Pravidla
    nedostupnosti: dict[str, tuple[int, ...]]
    nekompatibilni_dvojice: tuple[tuple[str, str], ...]
    vahy: Vahy

    @property
    def pocet_dni(self) -> int:
        return calendar.monthrange(self.rok, self.mesic)[1]

    @property
    def jmena(self) -> tuple[str, ...]:
        return tuple(z.jmeno for z in self.zamestnanci)

    def validovat(self) -> None:
        znama_jmena = set(self.jmena)
        if len(znama_jmena) != len(self.zamestnanci):
            raise ConfigError("Duplicitní jméno v seznamu zaměstnanců.")

        for jmeno, dny in self.nedostupnosti.items():
            if jmeno not in znama_jmena:
                raise ConfigError(f"Nedostupnost odkazuje na neznámého zaměstnance: {jmeno}")
            for den in dny:
                if not (1 <= den <= self.pocet_dni):
                    raise ConfigError(
                        f"Nedostupnost {jmeno}: den {den} je mimo měsíc "
                        f"(1-{self.pocet_dni})."
                    )

        for a, b in self.nekompatibilni_dvojice:
            for jmeno in (a, b):
                if jmeno not in znama_jmena:
                    raise ConfigError(
                        f"Neslučitelná dvojice odkazuje na neznámého zaměstnance: {jmeno}"
                    )

        o = self.obsazeni
        if not (0 <= o.denni_min <= o.denni_max):
            raise ConfigError("obsazeni: denni_min musí být <= denni_max a >= 0.")
        if not (0 <= o.nocni_min <= o.nocni_max):
            raise ConfigError("obsazeni: nocni_min musí být <= nocni_max a >= 0.")
        if self.pravidla.max_v_rade < 1:
            raise ConfigError("pravidla.max_v_rade musí být alespoň 1.")
        if self.pravidla.max_smen_mesic < 1:
            raise ConfigError("pravidla.max_smen_mesic musí být alespoň 1.")


def _nacti_zamestnance(data: list[dict]) -> tuple[Employee, ...]:
    return tuple(
        Employee(jmeno=z["jmeno"], stitky=tuple(z.get("stitky", [])))
        for z in data
    )


def _nacti_nedostupnosti(data: dict) -> dict[str, tuple[int, ...]]:
    return {jmeno: tuple(dny) for jmeno, dny in (data or {}).items()}


def _nacti_dvojice(data: list[list[str]]) -> tuple[tuple[str, str], ...]:
    dvojice = []
    for dvojice_raw in data or []:
        if len(dvojice_raw) != 2:
            raise ConfigError(f"Neslučitelná dvojice musí mít 2 jména, dostal jsem: {dvojice_raw}")
        dvojice.append((dvojice_raw[0], dvojice_raw[1]))
    return tuple(dvojice)


def config_from_dict(data: dict) -> Config:
    """Sestaví a zvaliduje Config z parsovaného YAML/dict."""
    try:
        obsazeni = Obsazeni(**data["obsazeni"])
        pravidla = Pravidla(**data["pravidla"])
        vahy = Vahy(**(data.get("vahy") or {}))
        config = Config(
            rok=data["rok"],
            mesic=data["mesic"],
            zamestnanci=_nacti_zamestnance(data["zamestnanci"]),
            obsazeni=obsazeni,
            pravidla=pravidla,
            nedostupnosti=_nacti_nedostupnosti(data.get("nedostupnosti")),
            nekompatibilni_dvojice=_nacti_dvojice(data.get("nekompatibilni_dvojice")),
            vahy=vahy,
        )
    except KeyError as chybi:
        raise ConfigError(f"V konfiguraci chybí povinný klíč: {chybi}") from chybi
    except TypeError as e:
        raise ConfigError(f"Neplatná konfigurace: {e}") from e

    config.validovat()
    return config


def load_config(cesta: str | Path) -> Config:
    """Načte konfiguraci ze YAML souboru."""
    with open(cesta, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return config_from_dict(data)
