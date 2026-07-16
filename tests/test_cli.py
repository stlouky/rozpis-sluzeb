"""Testy CLI pro ruční práci s DB (db/cli.py)."""

import pytest

from db.cli import main

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
