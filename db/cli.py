"""Jednoduché CLI pro ruční práci s DB, než bude webové UI (fáze 3)."""

from __future__ import annotations

import argparse
import getpass
from datetime import date
from pathlib import Path

from solver.core import NelzeSestavitError, generate_schedule

from . import repository as repo
from .auth import hashovat_heslo
from .bridge import DEFAULT_CONFIG_YAML, config_pro_mesic

DEFAULT_DB = Path(__file__).resolve().parent.parent / "rozpis.db"


def _pripojit_a_inicializovat(cesta: Path):
    return repo.pripojit_a_inicializovat(cesta)


def _precist_heslo(zadane: str | None) -> str:
    """Vrátí heslo z --heslo (automatizace/testy), jinak bezpečně vyzve
    přes getpass (heslo se nepropisuje do shell historie ani `ps`)."""
    if zadane is not None:
        return zadane
    heslo = getpass.getpass("Heslo: ")
    if heslo != getpass.getpass("Heslo znovu: "):
        print("Hesla se neshodují.")
        raise SystemExit(1)
    return heslo


def _cmd_pridat_zamestnance(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    stitky = args.stitky.split(",") if args.stitky else []
    id_ = repo.pridat_zamestnance(
        conn, args.jmeno, date.fromisoformat(args.aktivni_od), stitky, args.max_smen_mesic
    )
    print(f"Zaměstnanec přidán, id={id_}")


def _cmd_deaktivovat_zamestnance(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    repo.deaktivovat_zamestnance(conn, args.id, date.fromisoformat(args.aktivni_do))
    print(f"Zaměstnanec {args.id} deaktivován od {args.aktivni_do}")


def _cmd_opravit_jmeno(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    repo.opravit_jmeno_zamestnance(conn, args.id, args.jmeno)
    print(f"Zaměstnanec {args.id} přejmenován na „{args.jmeno}“")


def _cmd_pridat_nedostupnost(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    id_ = repo.pridat_nedostupnost(
        conn,
        args.zamestnanec_id,
        date.fromisoformat(args.od),
        date.fromisoformat(args.do),
        args.typ,
        args.poznamka,
        args.zakazana_smena,
    )
    print(f"Nedostupnost přidána, id={id_}")


def _cmd_pridat_dvojici(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    id_ = repo.pridat_dvojici(conn, args.zamestnanec_a_id, args.zamestnanec_b_id, args.typ)
    print(f"Dvojice přidána, id={id_}")


def _cmd_vytvorit_uzivatele(args: argparse.Namespace) -> None:
    heslo = _precist_heslo(args.heslo)
    conn = _pripojit_a_inicializovat(Path(args.db))
    id_ = repo.vytvorit_uzivatele(conn, args.jmeno, hashovat_heslo(heslo), args.role)
    print(f"Uživatel vytvořen, id={id_}")


def _cmd_zmenit_heslo(args: argparse.Namespace) -> None:
    heslo = _precist_heslo(args.heslo)
    conn = _pripojit_a_inicializovat(Path(args.db))
    repo.zmenit_heslo(conn, args.id, hashovat_heslo(heslo))
    print(f"Heslo uživatele {args.id} změněno")


def _cmd_seznam_zamestnancu(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    datum = date.fromisoformat(args.datum) if args.datum else date.today()
    for z in repo.aktivni_zamestnanci(conn, datum):
        stitky = f"  [{z.stitky}]" if z.stitky else ""
        print(f"{z.id:>3}  {z.jmeno}{stitky}")


def _cmd_generuj(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    config = config_pro_mesic(conn, args.rok, args.mesic, Path(args.config_yaml))
    try:
        schedule = generate_schedule(config)
    except NelzeSestavitError as e:
        print(e)
        raise SystemExit(1)
    print(schedule.to_text())

    if args.pdf:
        from vystup.pdf import vygenerovat_pdf

        vygenerovat_pdf(schedule, args.pdf)
        print(f"\nPDF uloženo: {args.pdf}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ruční správa DB rozpisu služeb")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="cesta k SQLite souboru")
    sub = parser.add_subparsers(dest="prikaz", required=True)

    p = sub.add_parser("pridat-zamestnance", help="přidat nového zaměstnance")
    p.add_argument("jmeno")
    p.add_argument("aktivni_od", help="YYYY-MM-DD")
    p.add_argument("--stitky", help="čárkou oddělené štítky, např. fyzicka_vypomoc")
    p.add_argument(
        "--max-smen-mesic", type=int,
        help="individuální strop směn/měsíc (bez zadání = společný strop z config.yaml)",
    )
    p.set_defaults(func=_cmd_pridat_zamestnance)

    p = sub.add_parser("deaktivovat-zamestnance", help="nastavit datum odchodu (nikdy se nemaže)")
    p.add_argument("id", type=int)
    p.add_argument("aktivni_do", help="YYYY-MM-DD")
    p.set_defaults(func=_cmd_deaktivovat_zamestnance)

    p = sub.add_parser("opravit-jmeno", help="opravit chybně zapsané jméno (ne odchod - viz deaktivovat-zamestnance)")
    p.add_argument("id", type=int)
    p.add_argument("jmeno")
    p.set_defaults(func=_cmd_opravit_jmeno)

    p = sub.add_parser("pridat-nedostupnost", help="přidat nedostupnost (interval od-do)")
    p.add_argument("zamestnanec_id", type=int)
    p.add_argument("od", help="YYYY-MM-DD")
    p.add_argument("do", help="YYYY-MM-DD")
    p.add_argument("typ", choices=["DOV", "NEM", "OST", "POZADAVEK"])
    p.add_argument("--poznamka")
    p.add_argument(
        "--zakazana-smena",
        choices=["D", "N"],
        help="omezit jen na tento typ směny (bez zadání = celý den nedostupný)",
    )
    p.set_defaults(func=_cmd_pridat_nedostupnost)

    p = sub.add_parser("pridat-dvojici", help="zadat dvojici (měkkou nebo tvrdou)")
    p.add_argument("zamestnanec_a_id", type=int)
    p.add_argument("zamestnanec_b_id", type=int)
    p.add_argument(
        "--typ", choices=["rozprostrit", "zakazano"], default="rozprostrit",
        help="rozprostrit = měkké (penalizace), zakazano = tvrdé (nikdy spolu)",
    )
    p.set_defaults(func=_cmd_pridat_dvojici)

    p = sub.add_parser("vytvorit-uzivatele", help="vytvořit uživatelský účet pro web (bez registrace přes web)")
    p.add_argument("jmeno")
    p.add_argument("role", choices=["admin", "nahled"])
    p.add_argument("--heslo", help="bez zadání se bezpečně vyzve přes prompt (doporučeno)")
    p.set_defaults(func=_cmd_vytvorit_uzivatele)

    p = sub.add_parser("zmenit-heslo", help="změnit heslo existujícího uživatele")
    p.add_argument("id", type=int)
    p.add_argument("--heslo", help="bez zadání se bezpečně vyzve přes prompt (doporučeno)")
    p.set_defaults(func=_cmd_zmenit_heslo)

    p = sub.add_parser("seznam-zamestnancu", help="vypsat aktivní zaměstnance k datu")
    p.add_argument("--datum", help="YYYY-MM-DD, výchozí dnešek")
    p.set_defaults(func=_cmd_seznam_zamestnancu)

    p = sub.add_parser("generuj", help="vygenerovat rozpis pro měsíc ze stavu DB")
    p.add_argument("rok", type=int)
    p.add_argument("mesic", type=int)
    p.add_argument("--config-yaml", default=str(DEFAULT_CONFIG_YAML))
    p.add_argument("--pdf", help="navíc uložit A4 PDF pro nástěnku na tuto cestu")
    p.set_defaults(func=_cmd_generuj)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
