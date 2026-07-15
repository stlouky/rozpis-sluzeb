"""Testy PDF exportu (vystup/pdf.py)."""

from solver.config import config_from_dict
from solver.core import generate_schedule
from vystup.pdf import BARVA_DOV, BARVA_OST, STITEK_OST, _hlavni_tabulka, vygenerovat_pdf

ZAMESTNANCI_12 = [
    "Alena", "Bedrich", "Cyril", "Dana", "Emil", "Frantiska",
    "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]


def _schedule():
    config = config_from_dict(dict(
        rok=2026,
        mesic=8,
        zamestnanci=[{"jmeno": j} for j in ZAMESTNANCI_12],
        obsazeni=dict(denni_min=3, denni_max=4, nocni_min=2, nocni_max=2),
        pravidla=dict(max_v_rade=3, max_smen_mesic=15),
        nedostupnosti={},
        nekompatibilni_dvojice=[],
        vahy={},
    ))
    return generate_schedule(config, time_limit_s=10.0)


def test_vygenerovat_pdf_vytvori_validni_soubor(tmp_path):
    schedule = _schedule()
    cesta = tmp_path / "rozpis.pdf"

    vygenerovat_pdf(schedule, cesta)

    assert cesta.exists()
    obsah = cesta.read_bytes()
    assert obsah.startswith(b"%PDF")
    assert obsah.rstrip().endswith(b"%%EOF")
    assert len(obsah) > 2000  # ne jen prázdná/rozbitá stránka


def test_vygenerovat_pdf_prijme_i_retezcovou_cestu(tmp_path):
    schedule = _schedule()
    cesta = str(tmp_path / "rozpis_str.pdf")

    vygenerovat_pdf(schedule, cesta)

    assert (tmp_path / "rozpis_str.pdf").exists()


def _schedule_s_volnem():
    config = config_from_dict(dict(
        rok=2026,
        mesic=8,
        zamestnanci=[{"jmeno": j} for j in ZAMESTNANCI_12],
        obsazeni=dict(denni_min=3, denni_max=4, nocni_min=2, nocni_max=2),
        pravidla=dict(max_v_rade=3, max_smen_mesic=15),
        nedostupnosti={"Alena": [1], "Bedrich": [1]},
        duvody_nedostupnosti={"Alena": {1: "DOV"}, "Bedrich": {1: "OST"}},
        nekompatibilni_dvojice=[],
        vahy={},
    ))
    return generate_schedule(config, time_limit_s=10.0)


def test_dov_je_zelena_a_bez_textu():
    # Alena (řádek 2, seřazeno abecedně = ZAMESTNANCI_12[0]) má 1. den DOV.
    schedule = _schedule_s_volnem()
    tabulka = _hlavni_tabulka(schedule)

    assert tabulka._cellvalues[2][1] == ""
    assert ("BACKGROUND", (1, 2), (1, 2), BARVA_DOV) in tabulka._bkgrndcmds


def test_ost_ma_text_a_bilé_pozadí():
    # Bedrich (řádek 3) má 1. den OST - text "OST", bílá buňka i přes to,
    # že 1.8.2026 je sobota (jinak by sloupec byl podbarvený šedě).
    schedule = _schedule_s_volnem()
    tabulka = _hlavni_tabulka(schedule)

    assert tabulka._cellvalues[3][1] == STITEK_OST
    assert ("BACKGROUND", (1, 3), (1, 3), BARVA_OST) in tabulka._bkgrndcmds
