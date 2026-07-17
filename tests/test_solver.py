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


def _pocet_plne_obsazenych_dni(config, schedule):
    return sum(
        1
        for den in range(1, schedule.pocet_dni + 1)
        if schedule.obsazeni_dne(den)[0] == config.obsazeni.denni_max
    )


def test_plne_obsazeni_vaha_zvysuje_pocet_plne_obsazenych_dni():
    # měkké pravidlo (váha plne_obsazeni=10) preferuje 4 lidi na denní
    # směně místo minima 3 (noční je vždy plná i bez téhle váhy, protože
    # nocni_min==nocni_max==2 je tvrdé omezení bez volnosti). Bez váhy (0)
    # nemá solver důvod dávat přednost plnému obsazení před minimem.
    #
    # Bez pevného random_seed běží solver na víc vláknech (portfolio search)
    # a při váze 0 objektiv na počtu plných dnů vůbec nezávisí - mezi
    # rovnocennými řešeními se vybírá libovolně, takže počet plných dnů
    # kolísal mezi jednotlivými spuštěními (pozorováno 13 i 25/31 pro stejný
    # config). Pevný seed vynutí jedno vlákno (viz generate_schedule) a tedy
    # reprodukovatelný výsledek - srovnání zůstává na nerovnosti počtu dnů,
    # ne na přesné hodnotě objective, protože rovnocenných řešení je víc.
    SEED = 42
    config_s_vahou = zakladni_config()
    schedule_s_vahou = generate_schedule(
        config_s_vahou, time_limit_s=TIME_LIMIT, random_seed=SEED
    )
    config_bez_vahy = zakladni_config(
        vahy=dict(plne_obsazeni=0, ferovost_nocni=5, ferovost_vikendy=3,
                  ferovost_celkem=4, nekompatibilni_penalizace=8)
    )
    schedule_bez_vahy = generate_schedule(
        config_bez_vahy, time_limit_s=TIME_LIMIT, random_seed=SEED
    )

    plnych_s_vahou = _pocet_plne_obsazenych_dni(config_s_vahou, schedule_s_vahou)
    plnych_bez_vahy = _pocet_plne_obsazenych_dni(config_bez_vahy, schedule_bez_vahy)

    assert plnych_s_vahou > plnych_bez_vahy


def test_zakaz_nocni_pred_denni(zakladni_schedule):
    _, schedule = zakladni_schedule
    for jmeno in schedule.jmena:
        for den in range(1, schedule.pocet_dni):
            if schedule.smena_zamestnance(jmeno, den) == "N":
                assert schedule.smena_zamestnance(jmeno, den + 1) != "D"


def test_po_dvou_nocnich_dva_dny_volna(zakladni_schedule):
    _, schedule = zakladni_schedule
    for jmeno in schedule.jmena:
        for den in range(1, schedule.pocet_dni):
            if (
                schedule.smena_zamestnance(jmeno, den) == "N"
                and schedule.smena_zamestnance(jmeno, den + 1) == "N"
            ):
                if den + 2 <= schedule.pocet_dni:
                    assert schedule.smena_zamestnance(jmeno, den + 2) is None
                if den + 3 <= schedule.pocet_dni:
                    assert schedule.smena_zamestnance(jmeno, den + 3) is None


def test_zakaz_tri_nocnich_v_rade(zakladni_schedule):
    _, schedule = zakladni_schedule
    for jmeno in schedule.jmena:
        serie = 0
        for den in range(1, schedule.pocet_dni + 1):
            if schedule.smena_zamestnance(jmeno, den) == "N":
                serie += 1
                assert serie <= 2
            else:
                serie = 0


def _nejdelsi_serie(schedule, jmeno):
    nejdelsi = serie = 0
    for den in range(1, schedule.pocet_dni + 1):
        if schedule.smena_zamestnance(jmeno, den) is not None:
            serie += 1
            nejdelsi = max(nejdelsi, serie)
        else:
            serie = 0
    return nejdelsi


def test_max_smen_v_rade(zakladni_schedule):
    config, schedule = zakladni_schedule
    max_v_rade = config.pravidla.max_v_rade
    for jmeno in schedule.jmena:
        assert _nejdelsi_serie(schedule, jmeno) <= max_v_rade


@pytest.mark.parametrize("max_v_rade", [1, 2])
def test_max_v_rade_respektuje_hodnotu_z_configu(max_v_rade):
    # ne jen že výchozích 3 v základním configu náhodou vychází - i přísnější
    # hodnoty (1, 2) musí solver reálně dodržet, což dokazuje, že se čte
    # z config.pravidla.max_v_rade a není natvrdo zadrátovaná v core.py
    config = zakladni_config(pravidla=dict(max_v_rade=max_v_rade, max_smen_mesic=15))
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    for jmeno in schedule.jmena:
        assert _nejdelsi_serie(schedule, jmeno) <= max_v_rade


def test_max_v_rade_omezuje_pod_prirozenou_delku():
    # bez efektivního omezení (max_v_rade nastavený na celý měsíc) solver
    # přirozeně vytvoří série dlouhé 5 (ověřeno experimentálně) - výchozí
    # strop 3 tedy reálně něco ořezává, není to jen náhoda z jiných pravidel
    config = zakladni_config(pravidla=dict(max_v_rade=31, max_smen_mesic=15))
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    nejdelsi = max(_nejdelsi_serie(schedule, jmeno) for jmeno in schedule.jmena)
    assert nejdelsi > 3


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


def test_respektuje_zakazany_typ_smeny():
    # Alena nechce denní směnu 21. - noční ten den ok, jiné dny ok obojí
    config = zakladni_config(zakazane_smeny={"Alena": {21: ["D"]}})
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    assert schedule.smena_zamestnance("Alena", 21) != "D"


def test_zakazany_typ_smeny_nevyrazuje_z_celeho_dne():
    # na rozdíl od nedostupnosti musí zůstat k dispozici pro zbylý typ směny.
    # Aby to test ověřil tvrdě (ne jen jako preferenci optimalizace), nastaví
    # 21. přesně tolik dostupných lidí (5 = denni_min 3 + nocni_min 2), kolik
    # je potřeba minimálně - všech 5 tedy MUSÍ ten den sloužit a Alena, které
    # je D zakázané, tak nutně musí dostat N.
    ostatni_nedostupni = ["Frantiska", "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka"]
    config = zakladni_config(
        nedostupnosti={jmeno: [21] for jmeno in ostatni_nedostupni},
        zakazane_smeny={"Alena": {21: ["D"]}},
    )
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    pocet_d, pocet_n = schedule.obsazeni_dne(21)
    assert (pocet_d, pocet_n) == (3, 2)
    assert schedule.smena_zamestnance("Alena", 21) == "N"


def test_config_odmitne_neznameho_zamestnance_v_zakazanych_smenach():
    with pytest.raises(ConfigError):
        zakladni_config(zakazane_smeny={"Neexistujici": {1: ["D"]}})


def test_config_odmitne_neplatny_typ_zakazane_smeny():
    with pytest.raises(ConfigError):
        zakladni_config(zakazane_smeny={"Alena": {1: ["X"]}})


def test_individualni_strop_omezi_jen_dane_osoby(zakladni_schedule):
    # Alena má snížený strop (brigádnice) - ostatní zůstávají na společném
    # max_smen_mesic=15 z config.yaml, jen ona nesmí přes 5
    config = zakladni_config(max_smen_mesic_override={"Alena": 5})
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    assert schedule.souhrn_zamestnance("Alena")["smeny"] <= 5

    _, schedule_bez_stropu = zakladni_schedule
    # sanity - bez individuálního stropu by Alena běžně měla víc než 5 směn
    assert schedule_bez_stropu.souhrn_zamestnance("Alena")["smeny"] > 5


def test_config_odmitne_neznameho_zamestnance_v_individualnim_stropu():
    with pytest.raises(ConfigError):
        zakladni_config(max_smen_mesic_override={"Neexistujici": 5})


def test_config_odmitne_zaporny_individualni_strop():
    with pytest.raises(ConfigError):
        zakladni_config(max_smen_mesic_override={"Alena": -1})


def test_random_seed_je_deterministicky():
    config = zakladni_config()
    a = generate_schedule(config, time_limit_s=TIME_LIMIT, random_seed=42)
    b = generate_schedule(config, time_limit_s=TIME_LIMIT, random_seed=42)
    assert a.smeny == b.smeny


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


def test_zakazana_dvojice_nikdy_nesdili_smenu(zakladni_schedule):
    config = zakladni_config(zakazane_dvojice=[["Cyril", "Karel"]])
    schedule = generate_schedule(config, time_limit_s=TIME_LIMIT)
    for den in range(1, schedule.pocet_dni + 1):
        s_cyril = schedule.smena_zamestnance("Cyril", den)
        s_karel = schedule.smena_zamestnance("Karel", den)
        if s_cyril is not None and s_karel is not None:
            assert s_cyril != s_karel


def test_zakazana_dvojice_je_tvrda_i_kdyz_to_jinak_nejde():
    # na rozdíl od nekompatibilni_dvojice (měkké - penalizace, ale spolu smí,
    # když jinak nejde) je zakazane_dvojice nesplnitelné, i kdyby to znamenalo
    # žádné řešení: 2 lidé, noční potřebuje přesně oba každý den
    config = zakladni_config(
        zamestnanci=[{"jmeno": "Holfaier"}, {"jmeno": "Stloukal"}],
        obsazeni=dict(denni_min=0, denni_max=0, nocni_min=2, nocni_max=2),
        pravidla=dict(max_v_rade=31, max_smen_mesic=31),
        zakazane_dvojice=[["Holfaier", "Stloukal"]],
    )
    with pytest.raises(NelzeSestavitError):
        generate_schedule(config, time_limit_s=5.0)


def test_config_odmitne_neznameho_zamestnance_v_zakazane_dvojici():
    with pytest.raises(ConfigError):
        zakladni_config(zakazane_dvojice=[["Neexistujici", "Alena"]])


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
