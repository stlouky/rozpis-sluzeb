"""Výsledek generování rozpisu."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

CZ_DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]


@dataclass(frozen=True)
class Schedule:
    """Vygenerovaný rozpis pro jeden měsíc.

    smeny: (jmeno, den 1-indexovaný) -> 'D' nebo 'N'. Chybějící klíč = volno.
    """

    rok: int
    mesic: int
    jmena: tuple[str, ...]
    smeny: dict[tuple[str, int], str]
    status: str
    cas_reseni: float
    # Důvod nedostupnosti (DOV/NEM/OST/POZADAVEK) pro dny volna - jen pro
    # zobrazení (PDF), solver s tím dál nepracuje. Chybějící klíč = buď se
    # pracovalo, nebo důvod není znám (např. config.yaml bez duvody_nedostupnosti).
    duvody_nedostupnosti: dict[tuple[str, int], str] = field(default_factory=dict)

    @property
    def pocet_dni(self) -> int:
        import calendar

        return calendar.monthrange(self.rok, self.mesic)[1]

    def smena_zamestnance(self, jmeno: str, den: int) -> str | None:
        return self.smeny.get((jmeno, den))

    def duvod_nedostupnosti(self, jmeno: str, den: int) -> str | None:
        return self.duvody_nedostupnosti.get((jmeno, den))

    def obsazeni_dne(self, den: int) -> tuple[int, int]:
        """Vrátí (počet denních, počet nočních) směn pro daný den."""
        pocet_d = sum(1 for j in self.jmena if self.smeny.get((j, den)) == "D")
        pocet_n = sum(1 for j in self.jmena if self.smeny.get((j, den)) == "N")
        return pocet_d, pocet_n

    def je_vikend(self, den: int) -> bool:
        return date(self.rok, self.mesic, den).weekday() >= 5

    def souhrn_zamestnance(self, jmeno: str) -> dict[str, int]:
        dny = range(1, self.pocet_dni + 1)
        smen = sum(1 for d in dny if (jmeno, d) in self.smeny)
        nocnich = sum(1 for d in dny if self.smeny.get((jmeno, d)) == "N")
        vikendovych = sum(1 for d in dny if self.je_vikend(d) and (jmeno, d) in self.smeny)
        return {"smeny": smen, "nocni": nocnich, "vikendy": vikendovych}

    def to_text(self) -> str:
        """Textová reprezentace rozpisu (pro CLI / rychlou kontrolu)."""
        radky = [
            f"ROZPIS SLUŽEB {self.mesic}/{self.rok}  "
            f"(řešení: {self.status}, {self.cas_reseni:.1f}s)",
            "",
        ]

        jmena_kratka = [j[:4] for j in self.jmena]
        radky.append(
            "Den        " + " ".join(f"{j:>4}" for j in jmena_kratka) + "   Denní Noční"
        )
        radky.append("-" * (11 + 5 * len(self.jmena) + 14))

        for den in range(1, self.pocet_dni + 1):
            datum = date(self.rok, self.mesic, den)
            wd = CZ_DNY[datum.weekday()]
            znacka = "*" if datum.weekday() >= 5 else " "
            radek = f"{den:2}. {wd}{znacka}    "
            for jmeno in self.jmena:
                s = self.smeny.get((jmeno, den))
                radek += "   D " if s == "D" else "   N " if s == "N" else "   . "
            pocet_d, pocet_n = self.obsazeni_dne(den)
            radek += f"    {pocet_d}     {pocet_n}"
            radky.append(radek)

        radky.append("")
        radky.append("D=denní  N=noční  .=volno  *=víkend")
        radky.append("")
        radky.append("Souhrn na osobu:")
        radky.append(f"{'Jméno':<12} {'Směn':>4} {'Hodin':>5} {'Nočních':>7} {'Víkend':>6}")
        for jmeno in self.jmena:
            s = self.souhrn_zamestnance(jmeno)
            radky.append(
                f"{jmeno:<12} {s['smeny']:>4} {s['smeny']*12:>5} "
                f"{s['nocni']:>7} {s['vikendy']:>6}"
            )

        return "\n".join(radky)
