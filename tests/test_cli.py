"""Testy CLI pro ruční práci s DB (db/cli.py)."""

from datetime import date
from pathlib import Path

import pytest

from db import repository as repo
from db.auth import overit_heslo
from db.cli import main
from solver.schedule import Schedule

FIXTURES = Path(__file__).parent / "fixtures" / "import_txt"
ZAMESTNANCI_FIKTIVNI = FIXTURES / "zamestnanci_fiktivni.txt"
POZADAVKY_FIKTIVNI = FIXTURES / "pozadavky_fiktivni.txt"

VSICH_12 = [
    "Alena", "Bedřich", "Cyril", "Dana", "Emil", "Frantiska",
    "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]


def _pridat_12_zamestnancu(cesta_db):
    for jmeno in VSICH_12:
        main(["--db", str(cesta_db), "pridat-zamestnance", jmeno, "2020-01-01"])


def test_cli_vytvori_db_soubor_pri_prvnim_pouziti(tmp_path):
    cesta_db = tmp_path / "novy.db"
    assert not cesta_db.exists()
    main(["--db", str(cesta_db), "pridat-zamestnance", "Alena", "2020-01-01"])
    assert cesta_db.exists()


def test_cli_pridat_zamestnance_a_seznam(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    main(["--db", str(cesta_db), "pridat-zamestnance", "Alena", "2020-01-01"])
    main([
        "--db", str(cesta_db), "pridat-zamestnance", "Cyril", "2020-01-01",
        "--stitky", "fyzicka_vypomoc",
    ])
    capsys.readouterr()  # zahodit výstup z přidávání

    main(["--db", str(cesta_db), "seznam-zamestnancu", "--datum", "2026-01-01"])
    vystup = capsys.readouterr().out

    assert "Alena" in vystup
    assert "Cyril" in vystup
    assert "fyzicka_vypomoc" in vystup


def test_cli_deaktivovat_zamestnance_zmizi_ze_seznamu(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    main(["--db", str(cesta_db), "pridat-zamestnance", "Alena", "2020-01-01"])
    capsys.readouterr()

    # id=1, protože je to první zaměstnanec v čerstvé DB
    main(["--db", str(cesta_db), "deaktivovat-zamestnance", "1", "2026-06-30"])
    capsys.readouterr()

    main(["--db", str(cesta_db), "seznam-zamestnancu", "--datum", "2026-07-01"])
    vystup_po = capsys.readouterr().out
    assert "Alena" not in vystup_po

    main(["--db", str(cesta_db), "seznam-zamestnancu", "--datum", "2026-06-15"])
    vystup_pred = capsys.readouterr().out
    assert "Alena" in vystup_pred


def test_cli_opravit_jmeno(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    main(["--db", str(cesta_db), "pridat-zamestnance", "Adamcová Bezemková Andrea", "2020-01-01"])
    capsys.readouterr()

    main(["--db", str(cesta_db), "opravit-jmeno", "1", "Bezemková Andrea"])
    capsys.readouterr()

    main(["--db", str(cesta_db), "seznam-zamestnancu", "--datum", "2026-01-01"])
    vystup = capsys.readouterr().out
    assert "Bezemková Andrea" in vystup
    assert "Adamcová" not in vystup


def test_cli_pridat_nedostupnost_se_projevi_v_rozpisu(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    _pridat_12_zamestnancu(cesta_db)
    capsys.readouterr()

    main([
        "--db", str(cesta_db), "pridat-nedostupnost", "1",
        "2026-08-03", "2026-08-09", "DOV",
    ])
    capsys.readouterr()

    main(["--db", str(cesta_db), "generuj", "2026", "8"])
    vystup = capsys.readouterr().out

    assert "ROZPIS SLUŽEB" in vystup
    # Alena (id=1) nemá sloužit 3.-9. srpna - v jejím sloupci by měly být
    # na těch řádcích jen tečky (žádné D/N)
    radky = {radek[:3]: radek for radek in vystup.splitlines()}
    for den in (" 3.", " 4.", " 5.", " 6.", " 7.", " 8.", " 9."):
        assert den in radky
        prvni_sloupec = radky[den].split()[2]
        assert prvni_sloupec == "."


def test_cli_pridat_dvojici_zakazano_se_projevi_v_rozpisu(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    _pridat_12_zamestnancu(cesta_db)
    capsys.readouterr()

    # id 3 = Cyril, id 11 = Karel (pořadí ve VSICH_12); v jmena tuple jsou
    # tedy na 0-indexovaných pozicích 2 a 10 - v textovém řádku dne to podle
    # to_text() odpovídá split()[2+pozice] (viz sousední test s Alenou = split()[2]).
    main([
        "--db", str(cesta_db), "pridat-dvojici", "3", "11", "--typ", "zakazano",
    ])
    capsys.readouterr()

    main(["--db", str(cesta_db), "generuj", "2026", "8"])
    vystup = capsys.readouterr().out

    radky = {radek[:3]: radek for radek in vystup.splitlines()}
    for den in range(1, 32):
        klic = f"{den:2}."
        casti = radky[klic].split()
        smena_cyril, smena_karel = casti[4], casti[12]
        if smena_cyril != "." and smena_karel != ".":
            assert smena_cyril != smena_karel, f"den {den}: Cyril i Karel slouží {smena_cyril}"


def test_cli_generuj_nesplnitelne_zadani_vypise_duvod_a_vraci_chybu(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    # jen 2 zaměstnanci - min. obsazení (3 denní + 2 noční) je nesplnitelné
    main(["--db", str(cesta_db), "pridat-zamestnance", "Alena", "2020-01-01"])
    main(["--db", str(cesta_db), "pridat-zamestnance", "Bedřich", "2020-01-01"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as excinfo:
        main(["--db", str(cesta_db), "generuj", "2026", "8"])

    assert excinfo.value.code == 1
    vystup = capsys.readouterr().out
    assert "nelze sestavit" in vystup.lower()


def test_cli_generuj_s_pdf_ulozi_soubor(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    _pridat_12_zamestnancu(cesta_db)
    capsys.readouterr()

    cesta_pdf = tmp_path / "rozpis.pdf"
    main(["--db", str(cesta_db), "generuj", "2026", "8", "--pdf", str(cesta_pdf)])
    vystup = capsys.readouterr().out

    assert cesta_pdf.exists()
    assert cesta_pdf.read_bytes().startswith(b"%PDF")
    assert "PDF uloženo" in vystup


def test_cli_generuj_ulozi_smeny_do_db(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    _pridat_12_zamestnancu(cesta_db)
    capsys.readouterr()

    main(["--db", str(cesta_db), "generuj", "2026", "8"])
    vystup = capsys.readouterr().out
    assert "uložen do DB" in vystup

    conn = repo.pripojit(cesta_db)
    smeny = repo.smeny_v_mesici(conn, 2026, 8)

    # kompletní měsíc: každý den srpna má obsazení 3-4 denní / přesně 2
    # noční (viz CLAUDE.md) - ověřuje se přímo na tom, co se reálně
    # zapsalo do DB, ne na výstupu solveru
    for den in range(1, 32):
        smeny_dne = [s for s in smeny if s.datum == date(2026, 8, den)]
        pocet_d = sum(1 for s in smeny_dne if s.typ == "D")
        pocet_n = sum(1 for s in smeny_dne if s.typ == "N")
        assert 3 <= pocet_d <= 4, f"den {den}: {pocet_d} denních směn v DB"
        assert pocet_n == 2, f"den {den}: {pocet_n} nočních směn v DB"


def test_cli_generuj_vypise_preskocene_konflikty_se_zamcenou_smenou(tmp_path, capsys, monkeypatch):
    cesta_db = tmp_path / "test.db"
    _pridat_12_zamestnancu(cesta_db)
    capsys.readouterr()

    conn = repo.pripojit(cesta_db)
    zamestnanci = repo.aktivni_zamestnanci(conn, date(2026, 8, 1))
    jmeno = zamestnanci[0].jmeno
    jmena = tuple(z.jmeno for z in zamestnanci)

    puvodni = Schedule(rok=2026, mesic=8, jmena=jmena, smeny={(jmeno, 1): "D"},
                        status="OPTIMAL", cas_reseni=0.1)
    repo.ulozit_rozpis(conn, puvodni)
    smena = repo.smeny_v_mesici(conn, 2026, 8)[0]
    repo.zamknout_smeny(conn, [smena.id])

    # generate_schedule zfalšovaný monkeypatchem - solver sám o sobě je
    # nedeterministický bez explicitního seedu, takže by nešlo spolehlivě
    # vynutit kolizi přesně na zamčený den; testuje se jen to, že CLI
    # správně přečte a vypíše to, co ulozit_rozpis vrátí.
    konfliktni = Schedule(rok=2026, mesic=8, jmena=jmena, smeny={(jmeno, 1): "N"},
                           status="OPTIMAL", cas_reseni=0.05)
    monkeypatch.setattr("db.cli.generate_schedule", lambda config: konfliktni)

    main(["--db", str(cesta_db), "generuj", "2026", "8"])
    vystup = capsys.readouterr().out

    assert "1 směna(y) přeskočena" in vystup
    assert jmeno in vystup
    assert "zamčeno na D" in vystup
    assert "navrhoval N" in vystup

    # DB pořád má původní zamčenou hodnotu, ne tu z konfliktního rozpisu
    smena_po = repo.smeny_v_mesici(conn, 2026, 8)[0]
    assert smena_po.typ == "D"


def test_cli_vytvorit_uzivatele_s_heslem_z_flagu(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    main([
        "--db", str(cesta_db), "vytvorit-uzivatele", "vedouci", "admin",
        "--heslo", "tajneheslo123",
    ])
    vystup = capsys.readouterr().out
    assert "Uživatel vytvořen" in vystup

    conn = repo.pripojit(cesta_db)
    uzivatel = repo.uzivatel_podle_jmena(conn, "vedouci")
    assert uzivatel is not None
    assert uzivatel.role == "admin"
    assert overit_heslo("tajneheslo123", uzivatel.heslo_hash)
    assert uzivatel.heslo_hash != "tajneheslo123"  # nikdy plain text


def test_cli_zmenit_heslo(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    main([
        "--db", str(cesta_db), "vytvorit-uzivatele", "vedouci", "nahled",
        "--heslo", "puvodni123",
    ])
    capsys.readouterr()

    main(["--db", str(cesta_db), "zmenit-heslo", "1", "--heslo", "nove456"])
    vystup = capsys.readouterr().out
    assert "změněno" in vystup

    conn = repo.pripojit(cesta_db)
    uzivatel = repo.uzivatel_podle_id(conn, 1)
    assert overit_heslo("nove456", uzivatel.heslo_hash)
    assert not overit_heslo("puvodni123", uzivatel.heslo_hash)


def _import_fiktivni(cesta_db):
    main([
        "--db", str(cesta_db), "import-txt",
        str(ZAMESTNANCI_FIKTIVNI), str(POZADAVKY_FIKTIVNI), "--rok", "2026",
    ])


def test_import_txt_prida_zamestnance_a_nedostupnosti(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    with pytest.raises(SystemExit) as excinfo:
        _import_fiktivni(cesta_db)
    assert excinfo.value.code == 1  # jeden řádek s neznámým jménem v pozadavky_fiktivni.txt
    vystup = capsys.readouterr().out

    assert "3 zaměstnanců přidáno" in vystup
    assert "5 nedostupností přidáno" in vystup
    assert "neznámý zaměstnanec „Neznámá Osoba“" in vystup
    assert "neznámý typ nepřítomnosti" in vystup.lower()  # OST fallback hláška

    conn = repo.pripojit(cesta_db)
    zamestnanci = repo.vsichni_zamestnanci(conn)
    assert {z.jmeno for z in zamestnanci} == {
        "Testovská Anna", "Vzorková Bedřiška Karolína", "Ukázka Cyril",
    }
    assert all(z.aktivni_od == date(2026, 1, 1) for z in zamestnanci)

    id_testovska = next(z.id for z in zamestnanci if z.jmeno == "Testovská Anna")
    id_vzorkova = next(z.id for z in zamestnanci if z.jmeno == "Vzorková Bedřiška Karolína")
    id_uzazka = next(z.id for z in zamestnanci if z.jmeno == "Ukázka Cyril")

    nedostupnosti = repo.nedostupnosti_v_obdobi(conn, date(2026, 1, 1), date(2026, 12, 31))
    assert len(nedostupnosti) == 5

    dovolena = next(n for n in nedostupnosti if n.zamestnanec_id == id_testovska and n.typ == "DOV")
    assert dovolena.od == dovolena.do == date(2026, 3, 5)

    pozadavek_d = next(
        n for n in nedostupnosti if n.zamestnanec_id == id_testovska and n.zakazana_smena == "D"
    )
    assert pozadavek_d.typ == "POZADAVEK"
    assert pozadavek_d.od == date(2026, 3, 7)

    pozadavek_n = next(n for n in nedostupnosti if n.zamestnanec_id == id_vzorkova)
    assert pozadavek_n.typ == "POZADAVEK"
    assert pozadavek_n.zakazana_smena == "N"
    assert pozadavek_n.od == date(2026, 3, 1)
    assert pozadavek_n.do == date(2026, 3, 3)

    ost_zaznamy = [n for n in nedostupnosti if n.zamestnanec_id == id_uzazka]
    assert len(ost_zaznamy) == 2  # "volno" i neznámý popis oba padnou do OST
    assert all(n.typ == "OST" for n in ost_zaznamy)


def test_import_txt_je_idempotentni(tmp_path, capsys):
    cesta_db = tmp_path / "test.db"
    with pytest.raises(SystemExit):
        _import_fiktivni(cesta_db)
    capsys.readouterr()

    with pytest.raises(SystemExit):
        _import_fiktivni(cesta_db)
    vystup_druhy = capsys.readouterr().out

    assert "0 zaměstnanců přidáno" in vystup_druhy
    assert "3 přeskočeno" in vystup_druhy
    assert "0 nedostupností přidáno" in vystup_druhy
    assert "„Testovská Anna“ už existuje" in vystup_druhy

    conn = repo.pripojit(cesta_db)
    assert len(repo.vsichni_zamestnanci(conn)) == 3
    assert len(repo.nedostupnosti_v_obdobi(conn, date(2026, 1, 1), date(2026, 12, 31))) == 5
