"""Export rozpisu do PDF pro tisk na nástěnku.

A4 na šířku, mřížka zaměstnanec x den - barvy podle CLAUDE.md (žlutá D,
modrá N). Zelená pro DOV zatím chybí: Schedule nenese důvod volna (jen
smeny D/N), to je otázka pro fázi 3-4, až rozpis ponese i nedostupnosti.

Standardní PDF fonty (Helvetica) neumí českou diakritiku s háčkem
(č/ř/ě/š/ž) - proto je přibalený DejaVu Sans (fonts/), aby export
fungoval stejně i na serveru bez systémových fontů.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from solver.schedule import Schedule

CZ_DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

BARVA_DENNI = colors.HexColor("#FFE699")
BARVA_NOCNI = colors.HexColor("#9DC3E6")
BARVA_VIKEND = colors.HexColor("#EDEDED")
BARVA_MRIZKY = colors.HexColor("#BBBBBB")

FONT = "DejaVuSans"
FONT_TUCNY = "DejaVuSans-Bold"
_FONTY_DIR = Path(__file__).resolve().parent / "fonts"


def _zaregistrovat_fonty() -> None:
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(FONT, str(_FONTY_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_TUCNY, str(_FONTY_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_TUCNY, italic=FONT, boldItalic=FONT_TUCNY)


def _je_vikend(schedule: Schedule, den: int) -> bool:
    return date(schedule.rok, schedule.mesic, den).weekday() >= 5


def _hlavni_tabulka(schedule: Schedule) -> Table:
    dny = range(1, schedule.pocet_dni + 1)

    radek_cisel = ["Jméno"] + [str(d) for d in dny]
    radek_dnu = [""] + [CZ_DNY[date(schedule.rok, schedule.mesic, d).weekday()] for d in dny]
    data = [radek_cisel, radek_dnu]
    for jmeno in schedule.jmena:
        data.append([jmeno] + [schedule.smena_zamestnance(jmeno, d) or "" for d in dny])

    sloupec_jmeno = 38 * mm
    sirka_stranky = landscape(A4)[0] - 16 * mm
    sirka_dne = (sirka_stranky - sloupec_jmeno) / schedule.pocet_dni
    sirky = [sloupec_jmeno] + [sirka_dne] * schedule.pocet_dni

    tabulka = Table(data, colWidths=sirky, repeatRows=2)

    styl = [
        ("GRID", (0, 0), (-1, -1), 0.4, BARVA_MRIZKY),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("FONTNAME", (0, 0), (-1, 1), FONT_TUCNY),
        ("FONTNAME", (0, 2), (0, -1), FONT_TUCNY),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]

    for i, den in enumerate(dny):
        sloupec = i + 1
        if _je_vikend(schedule, den):
            styl.append(("BACKGROUND", (sloupec, 0), (sloupec, 1), BARVA_VIKEND))

    for radek, jmeno in enumerate(schedule.jmena, start=2):
        for i, den in enumerate(dny):
            sloupec = i + 1
            typ = schedule.smena_zamestnance(jmeno, den)
            if typ == "D":
                styl.append(("BACKGROUND", (sloupec, radek), (sloupec, radek), BARVA_DENNI))
            elif typ == "N":
                styl.append(("BACKGROUND", (sloupec, radek), (sloupec, radek), BARVA_NOCNI))

    tabulka.setStyle(TableStyle(styl))
    return tabulka


def _souhrn_tabulka(schedule: Schedule) -> Table:
    data = [["Jméno", "Směn", "Hodin", "Nočních", "Víkend"]]
    for jmeno in schedule.jmena:
        s = schedule.souhrn_zamestnance(jmeno)
        data.append([jmeno, s["smeny"], s["smeny"] * 12, s["nocni"], s["vikendy"]])

    tabulka = Table(data, colWidths=[45 * mm] + [20 * mm] * 4)
    tabulka.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, BARVA_MRIZKY),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), FONT_TUCNY),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]))
    return tabulka


def vygenerovat_pdf(schedule: Schedule, cesta: str | Path) -> None:
    """Vytiskne rozpis jako A4 PDF na šířku, vhodné pro nástěnku."""
    _zaregistrovat_fonty()

    dokument = SimpleDocTemplate(
        str(cesta),
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )
    styly = getSampleStyleSheet()
    styly["Title"].fontName = FONT_TUCNY
    styly["Normal"].fontName = FONT
    nazev_mesice = date(schedule.rok, schedule.mesic, 1).strftime("%m/%Y")

    prvky = [
        Paragraph(f"Rozpis služeb {nazev_mesice}", styly["Title"]),
        Paragraph(
            "D = denní, N = noční, prázdné = volno. "
            f"Řešení: {schedule.status}.",
            styly["Normal"],
        ),
        Spacer(1, 4 * mm),
        _hlavni_tabulka(schedule),
        Spacer(1, 6 * mm),
        _souhrn_tabulka(schedule),
    ]
    dokument.build(prvky)
