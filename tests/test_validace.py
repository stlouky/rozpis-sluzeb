"""Testy validátoru tvrdých pravidel (úkol 8, viz zadani-faze3-web.md)."""

from solver.config import config_from_dict
from solver.schedule import Schedule
from solver.validace import validovat_rozpis

VOLNE_OBSAZENI = dict(denni_min=0, denni_max=99, nocni_min=0, nocni_max=99)
VOLNA_PRAVIDLA = dict(max_v_rade=99, max_smen_mesic=99)


def _config(**prepsat):
    data = dict(
        rok=2026,
        mesic=8,
        zamestnanci=[{"jmeno": j} for j in prepsat.pop("zamestnanci", ["Alena", "Bedrich"])],
        obsazeni=prepsat.pop("obsazeni", VOLNE_OBSAZENI),
        pravidla=prepsat.pop("pravidla", VOLNA_PRAVIDLA),
        nedostupnosti=prepsat.pop("nedostupnosti", {}),
        nekompatibilni_dvojice=[],
        vahy={},
    )
    data.update(prepsat)
    return config_from_dict(data)


def _schedule(smeny, jmena=("Alena", "Bedrich")):
    return Schedule(rok=2026, mesic=8, jmena=jmena, smeny=smeny, status="TEST", cas_reseni=0.0)


def test_bez_poruseni_prazdny_seznam():
    config = _config()
    schedule = _schedule({("Alena", 1): "D", ("Bedrich", 1): "N"})
    assert validovat_rozpis(schedule, config) == []


# --- obsazení pod/nad limitem (jeden ze dvou zadaných testů) ---

def test_obsazeni_pod_minimem():
    config = _config(obsazeni=dict(denni_min=3, denni_max=4, nocni_min=2, nocni_max=2))
    schedule = _schedule({("Alena", 1): "D"})  # jen 1 denní, min je 3

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec is None and p.den == 1 and "pod minimem" in p.popis for p in poruseni
    )


def test_obsazeni_nad_maximem():
    config = _config(
        zamestnanci=["Alena", "Bedrich", "Cyril"],
        obsazeni=dict(denni_min=0, denni_max=1, nocni_min=0, nocni_max=99),
    )
    schedule = _schedule(
        {("Alena", 1): "D", ("Bedrich", 1): "D"}, jmena=("Alena", "Bedrich", "Cyril")
    )

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec is None and p.den == 1 and "nad maximem" in p.popis for p in poruseni
    )


def test_obsazeni_v_rozsahu_bez_poruseni():
    config = _config(obsazeni=dict(denni_min=1, denni_max=2, nocni_min=0, nocni_max=99))
    schedule = _schedule({("Alena", 1): "D"})

    poruseni_dne_1 = [p for p in validovat_rozpis(schedule, config) if p.den == 1]
    assert poruseni_dne_1 == []


# --- N -> D (druhý ze dvou zadaných testů) ---

def test_denni_hned_po_nocni_je_porusena():
    config = _config()
    schedule = _schedule({("Alena", 1): "N", ("Alena", 2): "D"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec == "Alena" and p.den == 2 and "po noční" in p.popis for p in poruseni
    )


def test_nocni_hned_po_nocni_neni_porusena():
    config = _config()
    schedule = _schedule({("Alena", 1): "N", ("Alena", 2): "N"})
    assert validovat_rozpis(schedule, config) == []


# --- fond přes limit (třetí ze zadaných testů) ---

def test_fond_pres_limit():
    config = _config(pravidla=dict(max_v_rade=99, max_smen_mesic=2))
    schedule = _schedule({("Alena", 1): "D", ("Alena", 3): "D", ("Alena", 5): "D"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec == "Alena" and "překračuje strop" in p.popis for p in poruseni
    )


def test_fond_v_limitu_bez_poruseni():
    config = _config(pravidla=dict(max_v_rade=99, max_smen_mesic=3))
    schedule = _schedule({("Alena", 1): "D", ("Alena", 3): "D", ("Alena", 5): "D"})
    assert validovat_rozpis(schedule, config) == []


# --- max v řadě, max noční v řadě ---

def test_vice_nez_max_v_rade():
    config = _config(pravidla=dict(max_v_rade=2, max_smen_mesic=99))
    schedule = _schedule({("Alena", 1): "D", ("Alena", 2): "D", ("Alena", 3): "D"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(p.zamestnanec == "Alena" and "v řadě" in p.popis for p in poruseni)


def test_tri_nocni_v_rade_je_porusena():
    config = _config()
    schedule = _schedule({("Alena", 1): "N", ("Alena", 2): "N", ("Alena", 3): "N"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(p.zamestnanec == "Alena" and "2 noční" in p.popis for p in poruseni)


def test_dve_nocni_v_rade_bez_treti_neni_porusena():
    config = _config()
    schedule = _schedule({("Alena", 1): "N", ("Alena", 2): "N"})
    assert validovat_rozpis(schedule, config) == []


def test_prace_den_po_jednom_dni_volna_po_2_nocnich_je_porusena():
    config = _config()
    schedule = _schedule({("Alena", 1): "N", ("Alena", 2): "N", ("Alena", 4): "D"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec == "Alena" and p.den == 4 and "volna po 2 nočních" in p.popis
        for p in poruseni
    )


def test_2_dny_volna_po_2_nocnich_neni_porusena():
    config = _config()
    schedule = _schedule({("Alena", 1): "N", ("Alena", 2): "N", ("Alena", 5): "D"})
    assert validovat_rozpis(schedule, config) == []


# --- zakázaná dvojice, nedostupnost, zakázaný typ směny ---

def test_zakazana_dvojice_spolu_je_porusena():
    config = _config(zakazane_dvojice=[["Alena", "Bedrich"]])
    schedule = _schedule({("Alena", 1): "D", ("Bedrich", 1): "D"})

    poruseni = validovat_rozpis(schedule, config)
    jmena_porusujicich = {p.zamestnanec for p in poruseni if p.den == 1}
    assert jmena_porusujicich == {"Alena", "Bedrich"}


def test_zakazana_dvojice_jiny_typ_smeny_neni_porusena():
    config = _config(zakazane_dvojice=[["Alena", "Bedrich"]])
    schedule = _schedule({("Alena", 1): "D", ("Bedrich", 1): "N"})
    assert validovat_rozpis(schedule, config) == []


def test_smena_v_den_nedostupnosti_je_porusena():
    config = _config(nedostupnosti={"Alena": [5]})
    schedule = _schedule({("Alena", 5): "D"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec == "Alena" and p.den == 5 and "nedostupnosti" in p.popis for p in poruseni
    )


def test_zakazany_typ_smeny_je_porusena():
    config = _config(zakazane_smeny={"Alena": {5: ("N",)}})
    schedule = _schedule({("Alena", 5): "N"})

    poruseni = validovat_rozpis(schedule, config)
    assert any(
        p.zamestnanec == "Alena" and p.den == 5 and "zakázaný typ" in p.popis for p in poruseni
    )


def test_zakazany_typ_smeny_zbyly_typ_neni_porusena():
    config = _config(zakazane_smeny={"Alena": {5: ("N",)}})
    schedule = _schedule({("Alena", 5): "D"})
    assert validovat_rozpis(schedule, config) == []
