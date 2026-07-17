"""Parsování textových importních souborů (zamestnanci.txt, pozadavky.txt).

Formát zjištěný z reálných (gitignorovaných - viz .gitignore) souborů:
- zamestnanci.txt: jedno celé jméno na řádek, tvar "Příjmení [Příjmení2]
  Jméno" (prázdné řádky se ignorují).
- pozadavky.txt: řádky "den.měsíc[ - den.měsíc], jméno, popis", bez roku
  (doplňuje se parametrem rok - viz db/cli.py). Jméno je typicky jen
  příjmení, ne celé jméno ze zamestnanci.txt.

Reálná data NIKDY do gitu (bezpečnostní invariant, viz CLAUDE.md) - testy
používají vlastní fiktivní fixture soubory se stejným formátem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .models import Zamestnanec

_DATUM_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*$")

# (vzor v popisu, typ nedostupnosti, zakazana_smena) - pořadí záměrné:
# specifičtější "ne denní/noční" vzory musí být před obecným "volno", jinak
# by je "volno" nemohlo předběhnout (v datech se ale nepřekrývají).
_TYP_VZORY: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"ne\s+denn", re.IGNORECASE), "POZADAVEK", "D"),
    (re.compile(r"ne\s+no[cč]n", re.IGNORECASE), "POZADAVEK", "N"),
    (re.compile(r"dovolen", re.IGNORECASE), "DOV", None),
    (re.compile(r"l[ée]ka[rř]", re.IGNORECASE), "OST", None),
    (re.compile(r"voln", re.IGNORECASE), "OST", None),
]


def rozpoznat_typ(popis: str) -> tuple[str, str | None] | None:
    """Vrátí (typ, zakazana_smena) podle klíčových slov v popisu, nebo None,
    když popis nesedí na žádný známý vzor - volající pak zvolí výchozí OST
    a nahlásí to (viz db/cli.py), místo tichého uhádnutí."""
    for vzor, typ, zakazana_smena in _TYP_VZORY:
        if vzor.search(popis):
            return typ, zakazana_smena
    return None


# "16.8, Michnová, končí (ve zkušební době)" NENÍ nedostupnost - je to
# konec pracovního poměru (zamestnanec.aktivni_do), ne den volna. Bez týhle
# výjimky by to rozpoznat_typ spadlo do OST fallbacku jako jednodenní
# nedostupnost a zaměstnanec by zůstal "aktivní" (a plánovatelný) i po
# svém posledním dni - viz db/cli.py._cmd_import_txt.
_KONEC_POMERU_VZOR = re.compile(r"kon[čc][ií]|ukonč|odchod|odch[aá]z", re.IGNORECASE)


def je_konec_pomeru(popis: str) -> bool:
    """True, když popis signalizuje konec pracovního poměru, ne nedostupnost."""
    return bool(_KONEC_POMERU_VZOR.search(popis))


def parsovat_datum(cast: str, rok: int) -> date:
    shoda = _DATUM_RE.match(cast)
    if not shoda:
        raise ValueError(f"nerozpoznaný formát data „{cast}“ (očekáváno D.M)")
    den, mesic = int(shoda.group(1)), int(shoda.group(2))
    return date(rok, mesic, den)


def parsovat_rozsah(cast: str, rok: int) -> tuple[date, date]:
    """'21.8' -> (21.8., 21.8.); '1.8 - 31.8' / '1.8-2.8' -> (1.8., 31.8.).
    Mezery kolem pomlčky v datech kolísají (viz reálný soubor), proto se
    prostě celá část kolem první pomlčky rozdělí a osekají mezery zvlášť.
    """
    cast = cast.strip()
    if "-" in cast:
        od_str, do_str = cast.split("-", 1)
        return parsovat_datum(od_str, rok), parsovat_datum(do_str, rok)
    d = parsovat_datum(cast, rok)
    return d, d


@dataclass(frozen=True)
class RadekPozadavku:
    cislo_radku: int
    od: date
    do: date
    jmeno: str
    popis: str


def parsovat_radek_pozadavku(cislo_radku: int, radek: str, rok: int) -> RadekPozadavku:
    """Vyhodí ValueError s čitelnou hláškou (vč. čísla řádku) při
    nerozpoznaném formátu - volající chybu sesbírá a vypíše, neukončuje
    import na první chybné položce (viz db/cli.py)."""
    casti = [c.strip() for c in radek.split(",")]
    if len(casti) < 3:
        raise ValueError(
            f"řádek {cislo_radku}: očekávány 3 části oddělené čárkou (datum, "
            f"jméno, popis), dostal jsem „{radek}“"
        )
    datum_cast, jmeno, popis = casti[0], casti[1], ",".join(casti[2:]).strip()
    try:
        od, do = parsovat_rozsah(datum_cast, rok)
    except ValueError as e:
        raise ValueError(f"řádek {cislo_radku}: {e}") from e
    return RadekPozadavku(cislo_radku=cislo_radku, od=od, do=do, jmeno=jmeno, popis=popis)


def najit_zamestnance(zamestnanci: list[Zamestnanec], hledane_jmeno: str) -> Zamestnanec | None:
    """Přesná shoda jména, jinak shoda na prefix (příjmení) - jména v
    zamestnanci.txt jsou ve tvaru "Příjmení [Příjmení2] Jméno", zatímco
    pozadavky.txt často uvádí jen příjmení. Vrátí None při 0 nebo >1
    shodách - volající to musí nahlásit jako chybu, ne hádat (viz
    db/cli.py: "neznámé jméno = chyba s výpisem")."""
    presne = [z for z in zamestnanci if z.jmeno == hledane_jmeno]
    if len(presne) == 1:
        return presne[0]

    prefix = [z for z in zamestnanci if z.jmeno.startswith(hledane_jmeno + " ")]
    if len(prefix) == 1:
        return prefix[0]

    return None
