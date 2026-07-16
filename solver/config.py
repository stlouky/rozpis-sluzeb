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
    # Důvod nedostupnosti (DOV/NEM/OST/POZADAVEK) na den, jen pro zobrazení
    # ve výstupu (PDF apod.) - solver sám důvod nepotřebuje, mu stačí
    # `nedostupnosti` výš. Volitelné: config.yaml jej nezadává, jen db/bridge.py.
    duvody_nedostupnosti: dict[str, dict[int, str]] = field(default_factory=dict)
    # Nedostupnost jen pro konkrétní typ směny (na rozdíl od `nedostupnosti`
    # výš, kde je celý den volno): jmeno -> {den -> ("D",) / ("N",) / ("D","N")}.
    # Např. "nechci denní, noční mi nevadí" - člověk zůstává k dispozici pro
    # zbylý typ směny, `nedostupnosti` by ho vyřadilo z celého dne.
    zakazane_smeny: dict[str, dict[int, tuple[str, ...]]] = field(default_factory=dict)
    # Individuální strop směn/měsíc pro konkrétního člověka (např. brigádník
    # se sníženou kapacitou) - přebije pravidla.max_smen_mesic jen pro něj.
    max_smen_mesic_override: dict[str, int] = field(default_factory=dict)

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

        for jmeno, dny in self.zakazane_smeny.items():
            if jmeno not in znama_jmena:
                raise ConfigError(f"Zakázaná směna odkazuje na neznámého zaměstnance: {jmeno}")
            for den, typy in dny.items():
                if not (1 <= den <= self.pocet_dni):
                    raise ConfigError(
                        f"Zakázaná směna {jmeno}: den {den} je mimo měsíc (1-{self.pocet_dni})."
                    )
                for typ in typy:
                    if typ not in ("D", "N"):
                        raise ConfigError(
                            f"Zakázaná směna {jmeno}, den {den}: neplatný typ „{typ}“ (jen D/N)."
                        )

        for jmeno, strop in self.max_smen_mesic_override.items():
            if jmeno not in znama_jmena:
                raise ConfigError(
                    f"Individuální strop směn odkazuje na neznámého zaměstnance: {jmeno}"
                )
            if strop < 0:
                raise ConfigError(f"Individuální strop směn {jmeno}: musí být >= 0.")

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


def _nacti_duvody_nedostupnosti(data: dict) -> dict[str, dict[int, str]]:
    return {jmeno: dict(dny) for jmeno, dny in (data or {}).items()}


def _nacti_zakazane_smeny(data: dict) -> dict[str, dict[int, tuple[str, ...]]]:
    return {
        jmeno: {den: tuple(typy) for den, typy in dny.items()}
        for jmeno, dny in (data or {}).items()
    }


def _nacti_max_smen_mesic_override(data: dict) -> dict[str, int]:
    return dict(data or {})


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
            duvody_nedostupnosti=_nacti_duvody_nedostupnosti(data.get("duvody_nedostupnosti")),
            zakazane_smeny=_nacti_zakazane_smeny(data.get("zakazane_smeny")),
            max_smen_mesic_override=_nacti_max_smen_mesic_override(
                data.get("max_smen_mesic_override")
            ),
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
