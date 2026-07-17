"""Jednoduché CLI pro ruční práci s DB, než bude webové UI (fáze 3)."""

from __future__ import annotations

import argparse
import getpass
from datetime import date
from pathlib import Path

from solver.core import NelzeSestavitError, generate_schedule

from . import repository as repo
from .auth import hashovat_heslo
from .bridge import DEFAULT_CONFIG_YAML, config_pro_mesic, souhrn_vstupu
from .cesta import vychozi_cesta_db
from .import_txt import je_konec_pomeru, najit_zamestnance, parsovat_radek_pozadavku, rozpoznat_typ


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


def _cmd_import_txt(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    rok = args.rok
    vychozi_aktivni_od = date(rok, 1, 1)

    pridano_zamestnancu = 0
    preskoceno_zamestnancu = 0
    with open(args.zamestnanci_soubor, encoding="utf-8-sig") as f:
        for radek in f:
            jmeno = radek.strip()
            if not jmeno:
                continue
            if repo.zamestnanec_podle_jmena(conn, jmeno) is not None:
                print(f"Zaměstnanec „{jmeno}“ už existuje, přeskočeno.")
                preskoceno_zamestnancu += 1
                continue
            repo.pridat_zamestnance(conn, jmeno, vychozi_aktivni_od)
            pridano_zamestnancu += 1

    # Načteno až PO importu zaměstnanců - stejným spuštěním nově přidaný
    # zaměstnanec tak jde napárovat i na nedostupnost ze stejného souboru.
    zamestnanci = repo.vsichni_zamestnanci(conn)

    pridano_nedostupnosti = 0
    pocet_deaktivaci = 0
    chyby: list[str] = []
    with open(args.pozadavky_soubor, encoding="utf-8-sig") as f:
        for cislo_radku, syrovy_radek in enumerate(f, start=1):
            radek = syrovy_radek.strip()
            if not radek:
                continue
            try:
                polozka = parsovat_radek_pozadavku(cislo_radku, radek, rok)
            except ValueError as e:
                chyby.append(str(e))
                continue

            zamestnanec = najit_zamestnance(zamestnanci, polozka.jmeno)
            if zamestnanec is None:
                chyby.append(f"řádek {cislo_radku}: neznámý zaměstnanec „{polozka.jmeno}“")
                continue

            if je_konec_pomeru(polozka.popis):
                # NENÍ nedostupnost - konec pracovního poměru jde do
                # zamestnanec.aktivni_do (poslední den = polozka.do,
                # včetně), ne jako jednodenní/vícedenní OST záznam, jinak
                # by zaměstnanec zůstal "aktivní" i po svém posledním dni.
                repo.deaktivovat_zamestnance(conn, zamestnanec.id, polozka.do)
                print(
                    f"Řádek {cislo_radku}: {polozka.jmeno} - konec pracovního poměru "
                    f"k {polozka.do.isoformat()} (nastaveno aktivni_do, NE nedostupnost)."
                )
                pocet_deaktivaci += 1
                continue

            vysledek = rozpoznat_typ(polozka.popis)
            if vysledek is None:
                # Dřív se tu hádal fallback na OST a jen se to vypsalo -
                # přesně tenhle vzorec (tichý odhad zapsaný do DB) jednou
                # už způsobil chybu (viz je_konec_pomeru výš, incident
                # s "končí (ve zkušební době)" mylně zapsaným jako OST).
                # Nerozpoznaný popis je teď chyba jako neznámé jméno -
                # radši se zastavit a nechat to doplnit v db/import_txt.py
                # nebo opravit v souboru, než tiše zapsat špatnou hodnotu.
                chyby.append(
                    f"řádek {cislo_radku}: nerozpoznaný typ nepřítomnosti "
                    f"„{polozka.popis}“ u {polozka.jmeno} - není to ani "
                    f"nedostupnost, ani konec poměru"
                )
                continue
            typ, zakazana_smena = vysledek

            # Idempotence: (zaměstnanec, od, do, typ) už existuje -> přeskočit.
            existujici = repo.nedostupnosti_v_obdobi(conn, polozka.od, polozka.do)
            duplicita = any(
                n.zamestnanec_id == zamestnanec.id
                and n.od == polozka.od
                and n.do == polozka.do
                and n.typ == typ
                for n in existujici
            )
            if duplicita:
                continue

            repo.pridat_nedostupnost(
                conn, zamestnanec.id, polozka.od, polozka.do, typ, zakazana_smena=zakazana_smena
            )
            pridano_nedostupnosti += 1

    print(
        f"\nSouhrn importu: {pridano_zamestnancu} zaměstnanců přidáno, "
        f"{preskoceno_zamestnancu} přeskočeno, "
        f"{pridano_nedostupnosti} nedostupností přidáno, "
        f"{pocet_deaktivaci} konec(ů) poměru zapsáno."
    )

    if chyby:
        print(f"\n{len(chyby)} chyba(y) při importu nedostupností:")
        for chyba in chyby:
            print(f"  - {chyba}")
        raise SystemExit(1)


def _cmd_seznam_zamestnancu(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))
    datum = date.fromisoformat(args.datum) if args.datum else date.today()
    for z in repo.aktivni_zamestnanci(conn, datum):
        stitky = f"  [{z.stitky}]" if z.stitky else ""
        print(f"{z.id:>3}  {z.jmeno}{stitky}")


def _cmd_generuj(args: argparse.Namespace) -> None:
    conn = _pripojit_a_inicializovat(Path(args.db))

    pocet_zamestnancu, pocet_nedostupnosti = souhrn_vstupu(conn, args.rok, args.mesic)
    print(
        f"Vstup: {pocet_zamestnancu} zaměstnanců, {pocet_nedostupnosti} nedostupností "
        f"pro {args.rok}-{args.mesic:02d}"
    )
    if pocet_nedostupnosti == 0:
        print(
            "UPOZORNĚNÍ: pro tenhle měsíc není v DB žádná nedostupnost - pokud jsi "
            "čekal(a) DOV/NEM/omezení směn, zkontroluj, že proběhl import "
            "(např. import-txt) PŘED generováním. Bez nedostupností solver počítá "
            "s tím, že má každý úplně volnou ruku.\n"
        )

    config = config_pro_mesic(conn, args.rok, args.mesic, Path(args.config_yaml))
    try:
        schedule = generate_schedule(config)
    except NelzeSestavitError as e:
        print(e)
        raise SystemExit(1)

    preskocene = repo.ulozit_rozpis(conn, schedule)

    print(schedule.to_text())
    print(f"\nRozpis uložen do DB ({args.db}).")

    if preskocene:
        print(f"\n{len(preskocene)} směna(y) přeskočena kvůli zamčené kolizi:")
        for p in preskocene:
            print(
                f"  - {p.jmeno} {p.datum.isoformat()}: zamčeno na {p.puvodni_typ}, "
                f"nový rozpis navrhoval {p.novy_typ} - ponechána zamčená hodnota"
            )

    if args.pdf:
        from vystup.pdf import vygenerovat_pdf

        vygenerovat_pdf(schedule, args.pdf)
        print(f"\nPDF uloženo: {args.pdf}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ruční správa DB rozpisu služeb")
    parser.add_argument(
        "--db", default=str(vychozi_cesta_db()),
        help="cesta k SQLite souboru (výchozí: $ROZPIS_DB, jinak data/rozpis.db)",
    )
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

    p = sub.add_parser(
        "import-txt",
        help="hromadný import zaměstnanců a nedostupností z textových souborů",
    )
    p.add_argument("zamestnanci_soubor")
    p.add_argument("pozadavky_soubor")
    p.add_argument(
        "--rok", type=int, default=2026,
        help="rok pro data bez roku v souboru nedostupností a výchozí aktivni_od "
             "(YYYY-01-01), výchozí 2026",
    )
    p.set_defaults(func=_cmd_import_txt)

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
