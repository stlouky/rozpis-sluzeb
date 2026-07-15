"""Testy tvrdých pravidel solveru (viz CLAUDE.md)."""

import yaml
import pytest

from solver.config import ConfigError, config_from_dict, load_config
from solver.core import NelzeSestavitError, generate_schedule

TIME_LIMIT = 10.0

ZAMESTNANCI_12 = [
    "Alena", "Bedrich", "Cyril", "Dana", "Emil", "Frantiska",
    "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]


def zakladni_config(**overrides):
    data = dict(
        rok=2026,
        mesic=8,  # srpen, 31 dní
        zamestnanci=[{"jmeno": j} for j in ZAMESTNANCI_12],
        obsazeni=dict(denni_min=3, denni_max=4, nocni_min=2, nocni_max=2),
        pravidla=dict(max_v_rade=3, max_smen_mesic=15),
        nedostupnosti={},
        nekompatibilni_dvojice=[],
        vahy={},
    )
    data.update(overrides)
    return config_from_dict(data)


@pytest.fixture(scope="module")
def zakladni_schedule():
    """Jeden vyřešený rozpis sdílený mezi testy tvrdých pravidel (solve je pomalý)."""
    config = zakladni_config()
    return config, generate_schedule(config, time_limit_s=TIME_LIMIT)


def test_obsazeni_denni_v_mezich(zakladni_schedule):
    config, schedule = zakladni_schedule
    for den in range(1, schedule.pocet_dni + 1):
        pocet_d, _ = schedule.obsazeni_dne(den)
        assert config.obsazeni.denni_min <= pocet_d <= config.obsazeni.denni_max


def test_obsazeni_nocni_presne_dve(zakladni_schedule):
    _, schedule = zakladni_schedule
    for den in range(1, schedule.pocet_dni + 1):
        _, pocet_n = schedule.obsazeni_dne(den)
        assert pocet_n == 2


def test_obsazeni_plati_i_o_vikendu(zakladni_schedule):
    # CLAUDE.md: obsazení 3-4 denní / přesně 2 noční platí "každý den vč.
    # víkendů a svátků" - v configu/modelu neexistuje žádná víkendová
    # výjimka (obsazeni constraint běží stejně pro všechny dny), tenhle
    # test to ověřuje explicitně a odděleně od test_obsazeni_*_v_mezich,
    # aby budoucí "víkendová výjimka" nemohla proklouznout bez povšimnutí
    config, schedule = zakladni_schedule
    vikendove_dny = [d for d in range(1, schedule.pocet_dni + 1) if schedule.je_vikend(d)]
    assert vikendove_dny  # sanity - v testovaném měsíci víkend skutečně je
    for den in vikendove_dny:
        pocet_d, pocet_n = schedule.obsazeni_dne(den)
        assert config.obsazeni.denni_min <= pocet_d <= config.obsazeni.denni_max
        assert pocet_n == 2


def test_zakaz_nocni_pred_denni(zakladni_schedule):
    _, schedule = zakladni_schedule
    for jmeno in schedule.jmena:
        for den in range(1, schedule.pocet_dni):
            if schedule.smena_zamestnance(jmeno, den) == "N":
                assert schedule.smena_zamestnance(jmeno, den + 1) != "D"


def test_max_smen_v_rade(zakladni_schedule):
    config, schedule = zakladni_schedule
    max_v_rade = config.pravidla.max_v_rade
    for jmeno in schedule.jmena:
        v_rade = 0
        for den in range(1, schedule.pocet_dni + 1):
            if schedule.smena_zamestnance(jmeno, den) is not None:
                v_rade += 1
                assert v_rade <= max_v_rade
            else:
                v_rade = 0


def test_max_jedna_smena_denne(zakladni_schedule):
    # generate_schedule interně assertuje, že žádná osoba nemá D i N ve
    # stejný den (viz core.py) - pokud by CP-SAT constraint selhal, fixture
    # by shodila celý modul testů. Tady navíc ověříme tvar výstupu.
    _, schedule = zakladni_schedule
    for typ in schedule.smeny.values():
        assert typ in ("D", "N")


def test_fond_hodin_dodrzen(zakladni_schedule):
    config, schedule = zakladni_schedule
    for jmeno in schedule.jmena:
        souhrn = schedule.souhrn_zamestnance(jmeno)
        assert souhrn["smeny"] <= config.pravidla.max_smen_mesic


def test_fond_hodin_omezuje_pod_prirozenou_rovnovahu():
    # bez omezení (max_smen_mesic vysoko) by solver dal některým lidem
    # 16 směn (ověřeno experimentálně) - přísnější strop 13 (těsně nad
    # agregátním minimem 12*13=156 >= 155 potřebných) musí reálně useknout
    # každého, ne jen náhodou sedět na přirozeném maximu jako v základním
    # configu (tam je strop 15 blízko přirozenému stropu 16)
    config = zakladni_config(pravidla=dict(max_v_rade=3, max_smen_mesic=13))
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    for jmeno in schedule.jmena:
        assert schedule.souhrn_zamestnance(jmeno)["smeny"] <= 13


def test_ferove_rozdeleni_nocnich_vikendovych_a_celkovych_smen(zakladni_schedule):
    # měkké pravidlo (váhy 5/3/4) - při rovnoměrné dostupnosti všech 12 lidí
    # po celý měsíc by rozptyl mezi nejvytíženějším a nejméně vytíženým
    # člověkem měl být malý, ne nutně nulový
    _, schedule = zakladni_schedule
    nocni = [schedule.souhrn_zamestnance(j)["nocni"] for j in schedule.jmena]
    vikendy = [schedule.souhrn_zamestnance(j)["vikendy"] for j in schedule.jmena]
    celkem = [schedule.souhrn_zamestnance(j)["smeny"] for j in schedule.jmena]
    assert max(nocni) - min(nocni) <= 2
    assert max(vikendy) - min(vikendy) <= 2
    assert max(celkem) - min(celkem) <= 2


def test_respektuje_nedostupnosti():
    dny_volna = [3, 4, 5, 6, 7, 8, 9]
    config = zakladni_config(nedostupnosti={"Alena": dny_volna})
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    for den in dny_volna:
        assert schedule.smena_zamestnance("Alena", den) is None


def test_respektuje_nedostupnosti_vice_lidi_najednou():
    # reálný případ z config.yaml: víc lidí má současně různé požadavky
    # na volno (dovolená přes víc dní i jednotlivé dny) - ověřuje, že se
    # loop přes všechny položky v nedostupnosti neomezuje jen na jednu
    pozadavky = {
        "Alena": [3, 4, 5, 6, 7, 8, 9],
        "Dana": [14, 15],
        "Gustav": [20, 21, 22, 23, 24, 25, 26],
        "Jitka": [1, 2],
        "Karel": [28, 29, 30],
    }
    config = zakladni_config(nedostupnosti=pozadavky)
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    for jmeno, dny_volna in pozadavky.items():
        for den in dny_volna:
            assert schedule.smena_zamestnance(jmeno, den) is None, (
                f"{jmeno} má sloužit {den}., ačkoli má ten den nahlášené volno"
            )


def test_config_odmitne_den_mimo_rozsah_mesice():
    # srpen 2026 má 31 dní - den 32 je mimo měsíc
    with pytest.raises(ConfigError):
        zakladni_config(nedostupnosti={"Alena": [32]})
    with pytest.raises(ConfigError):
        zakladni_config(nedostupnosti={"Alena": [0]})


def test_nekompatibilni_dvojice_se_vyhybaji_spolecne_smene():
    # měkké pravidlo (penalizace 8) - při dostatku lidí je vyhnutí se dvojici
    # "zadarmo", takže optimální řešení by je nemělo nikdy potkat pohromadě
    config = zakladni_config(nekompatibilni_dvojice=[["Cyril", "Karel"]])
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    for den in range(1, schedule.pocet_dni + 1):
        smena_cyril = schedule.smena_zamestnance("Cyril", den)
        smena_karel = schedule.smena_zamestnance("Karel", den)
        if smena_cyril is not None and smena_karel is not None:
            assert smena_cyril != smena_karel, (
                f"den {den}: Cyril i Karel slouží stejnou směnu ({smena_cyril}), "
                "ačkoli je to neslučitelná dvojice a obsazení to nevyžaduje"
            )


def test_nesplnitelne_zadani_vyhazuje_chybu_s_duvodem():
    # jen 2 lidé, ale potřeba min. 5 (3 denní + 2 noční) -> nesplnitelné
    # (spustí obě heuristiky najednou, viz izolované testy níže)
    config = zakladni_config(zamestnanci=[{"jmeno": "Alena"}, {"jmeno": "Bedrich"}])
    with pytest.raises(NelzeSestavitError) as excinfo:
        generate_schedule(config, time_limit_s=5.0)
    assert excinfo.value.duvody
    assert any("Den" in d or "kapacita" in d.lower() for d in excinfo.value.duvody)


def test_diagnostika_odhali_podstav_v_konkretnim_dni():
    # 12 lidí je jinak dost, ale 10 z nich má týž den (15.) volno -> zbydou
    # jen 2 dostupní, což nestačí na minimum 5. Celková kapacita fondu
    # hodin přitom zůstává v pořádku, takže by se NEMĚLA spustit i
    # kapacitní heuristika - izoluje to hlášku "Den X."
    nedostupny_den = 15
    nedostupnosti = {jmeno: [nedostupny_den] for jmeno in ZAMESTNANCI_12[:10]}
    config = zakladni_config(nedostupnosti=nedostupnosti)
    with pytest.raises(NelzeSestavitError) as excinfo:
        generate_schedule(config, time_limit_s=5.0)
    assert any(f"Den {nedostupny_den}." in d for d in excinfo.value.duvody)
    assert not any("kapacita" in d.lower() for d in excinfo.value.duvody)


def test_diagnostika_odhali_nedostatek_celkove_kapacity():
    # 12 lidí je každý den plně k dispozici (žádná nedostupnost), ale fond
    # hodin (max_smen_mesic=3) na pokrytí měsíce zdaleka nestačí -> izoluje
    # to hlášku o celkové kapacitě bez jediné hlášky o konkrétním dni
    config = zakladni_config(pravidla=dict(max_v_rade=3, max_smen_mesic=3))
    with pytest.raises(NelzeSestavitError) as excinfo:
        generate_schedule(config, time_limit_s=5.0)
    assert any("kapacita" in d.lower() for d in excinfo.value.duvody)
    assert not any("Den " in d for d in excinfo.value.duvody)


def test_nesplnitelnost_bez_zjevne_priciny_pouzije_obecnou_hlasku():
    # 6 lidí, denně musí pracovat přesně 5 (3 denní + 2 noční, min == max),
    # tedy vždy odpočívá právě 1 člověk. Aby nikdo nepřesáhl max_v_rade=3
    # dny v řadě, musel by si v každém 4denním okně odpočinout každý ze 6
    # lidí - ale k dispozici jsou jen 4 volné sloty (1/den). Holubníkový
    # princip -> nesplnitelné, avšak obě heuristiky to nezachytí (obsazení
    # denně stačí, fond hodin na celý měsíc taky), takže musí spadnout do
    # obecné fallback hlášky v core.py.
    config = zakladni_config(
        rok=2026,
        mesic=2,  # únor 2026, 28 dní
        zamestnanci=[{"jmeno": j} for j in ["A", "B", "C", "D", "E", "F"]],
        obsazeni=dict(denni_min=3, denni_max=3, nocni_min=2, nocni_max=2),
        pravidla=dict(max_v_rade=3, max_smen_mesic=28),
    )
    with pytest.raises(NelzeSestavitError) as excinfo:
        generate_schedule(config, time_limit_s=15.0)
    assert len(excinfo.value.duvody) == 1
    assert "automatická diagnostika" in excinfo.value.duvody[0]


def test_config_odmitne_neznameho_zamestnance_v_nedostupnostech():
    with pytest.raises(ConfigError):
        zakladni_config(nedostupnosti={"Neexistujici": [1, 2]})


def test_config_odmitne_neplatne_obsazeni():
    with pytest.raises(ConfigError):
        zakladni_config(obsazeni=dict(denni_min=5, denni_max=3, nocni_min=2, nocni_max=2))


def test_load_config_ze_souboru(tmp_path):
    obsah = {
        "rok": 2026,
        "mesic": 2,  # únor 2026, 28 dní
        "zamestnanci": [{"jmeno": j} for j in ["A", "B", "C", "D", "E"]],
        "obsazeni": {"denni_min": 1, "denni_max": 2, "nocni_min": 1, "nocni_max": 1},
        "pravidla": {"max_v_rade": 3, "max_smen_mesic": 20},
    }
    soubor = tmp_path / "test_config.yaml"
    soubor.write_text(yaml.safe_dump(obsah, allow_unicode=True), encoding="utf-8")

    config = load_config(soubor)

    assert config.rok == 2026
    assert len(config.zamestnanci) == 5
