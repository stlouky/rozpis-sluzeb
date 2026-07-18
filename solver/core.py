"""Generování rozpisu pomocí OR-Tools CP-SAT.

Čisté API: generate_schedule(config) -> Schedule.
Při nesplnitelnosti vyhazuje NelzeSestavitError s výčtem kolidujících
dnů/pravidel (viz CLAUDE.md: "při nesplnitelnosti VŽDY vypsat proč").
"""

from __future__ import annotations

from datetime import date

from ortools.sat.python import cp_model

from .config import Config
from .schedule import Schedule


class NelzeSestavitError(Exception):
    """Zadání je nesplnitelné — solver nenašel žádné přípustné řešení."""

    def __init__(self, duvody: list[str]):
        zprava = "Rozpis nelze sestavit — nesplnitelná pravidla:\n" + "\n".join(
            f"  - {d}" for d in duvody
        )
        super().__init__(zprava)
        self.duvody = duvody


def _diagnostikuj_nesplnitelnost(config: Config) -> list[str]:
    """Heuristicky odhalí nejčastější příčiny nesplnitelnosti bez nutnosti
    volat solver znovu: podstav dostupných lidí v konkrétní den a nedostatek
    celkové kapacity vůči fondu hodin.
    """
    duvody: list[str] = []
    nedostupny = {jmeno: set(dny) for jmeno, dny in config.nedostupnosti.items()}
    pocet_dni = config.pocet_dni
    o = config.obsazeni

    for den in range(1, pocet_dni + 1):
        dostupni = [z for z in config.jmena if den not in nedostupny.get(z, set())]
        potreba_min = o.denni_min + o.nocni_min
        if len(dostupni) < potreba_min:
            duvody.append(
                f"Den {den}.: dostupných je jen {len(dostupni)} lidí, "
                f"ale minimální obsazení vyžaduje {potreba_min} "
                f"(denní {o.denni_min} + noční {o.nocni_min})."
            )

    potreba_min_celkem = pocet_dni * (o.denni_min + o.nocni_min)
    kapacita_celkem = sum(
        min(
            config.max_smen_mesic_override.get(jmeno, config.pravidla.max_smen_mesic),
            pocet_dni - len(nedostupny.get(jmeno, set())),
        )
        for jmeno in config.jmena
    )
    if kapacita_celkem < potreba_min_celkem:
        duvody.append(
            f"Celková kapacita všech zaměstnanců ({kapacita_celkem} směn/měsíc) "
            f"nestačí na minimální měsíční potřebu ({potreba_min_celkem} směn) — "
            f"zkontrolujte fond hodin (max_smen_mesic="
            f"{config.pravidla.max_smen_mesic}) a nedostupnosti."
        )

    return duvody


_VIKENDOVY_FAKTOR_VSEDNI_DEN = 3
_PONDELI_DALSI_FAKTOR = 3
_VAHA_SOULAD_VIKENDU = 8
_VAHA_NEZKUSENI_BEZ_DOZORU = 6


def generate_schedule(
    config: Config,
    time_limit_s: float = 30.0,
    random_seed: int | None = None,
    prioritizovat_obsazeni: bool = False,
    preferovat_krizove_o_vikendu: bool = False,
    krizove_jen_o_vikendu: bool = False,
    preferovat_stejnou_smenu_o_vikendu: bool = False,
    vyhnout_se_pondeli: bool = False,
    nezkuseni: tuple[str, ...] = (),
) -> Schedule:
    """Vygeneruje rozpis pro daný config.

    vyhnout_se_pondeli: měkká preference (na přání, jen pro jedno konkrétní
    generování - "zkus to tak, aby krizový den nebyl pondělí") - mezi
    všedními dny dá pondělí ještě vyšší váhu plného obsazení než zbytek
    týdne (nad rámec preferovat_krizove_o_vikendu), takže pokud je po
    vyčerpání víkendů (viz krizove_jen_o_vikendu) pořád potřeba krizový
    všední den, solver upřednostní úterý-pátek před pondělím. Není to
    záruka (může prohrát, když je pondělí jediný den, co reálně nejde
    zaplnit).

    nezkuseni: jména lidí, u kterých se (měkce) penalizuje, když jsou na
    směně (D i N) BEZ jediného zkušeného kolegy - na přání ("nováčci/
    brigádníci nevěděli, co mají dělat"). Prázdné jméno navíc v seznamu se
    ignoruje (config nemusí všechny vždycky znát).

    random_seed: při nezměněném configu ovlivní, ke kterému z rovnocenně
    optimálních řešení solver dojde - použitelné pro nabídku více variant
    rozpisu ke stejnému zadání (stejný seed = stejný výsledek).

    preferovat_stejnou_smenu_o_vikendu: měkká preference (na přání - "je
    zvyklost, že víkendová směna bývá oba dny stejná") - bonus v cíli za
    to, že člověk má v sobotu a neděli STEJNÝ typ (D+D, N+N, nebo oba
    volno), ne rozdílný (D+N, D+volno apod.). Neplatí jako tvrdé pravidlo
    (může to prohrát proti fondu hodin/férovosti/nedostupnostem) - je to
    jen zvyklost, ne pravidlo z CLAUDE.md.

    preferovat_krizove_o_vikendu: když víc plně obsazených D/N slotů nejde
    dosáhnout současně (krizový den je nevyhnutelný), preferuje, aby
    nedostatek padl na sobotu/neděli, ne na všední den (na přání). Funguje
    tak, že plné obsazení ve všední den má v cíli vyšší váhu než o víkendu
    (_VIKENDOVY_FAKTOR_VSEDNI_DEN) - CELKOVÝ počet plně obsazených dnů
    (plna_promenne, viz prioritizovat_obsazeni níž) tím zůstává beze změny,
    ovlivní se jen KTERÉ dny jsou ty plné, když je nutné vybírat. Beze změny
    (výchozí False), pokud tenhle výběr nezáleží. Na rozdíl od
    krizove_jen_o_vikendu níž je tohle jen PREFERENCE (měkká, může selhat na
    strukturálně vynucených krizových dnech, viz test), ne záruka.

    krizove_jen_o_vikendu: TVRDĚ vynutí pořadí, ve kterém se "spotřebovává"
    nevyhnutelný nedostatek (na přání, upřesněno: NENÍ to absolutní zákaz
    krizového všedního dne, je to PRIORITA) - krizový den v pondělí až
    pátek smí nastat JEN když jsou už krizové VŠECHNY víkendové dny v
    měsíci (jinak by šlo "ušetřit" víkend na úkor všedního dne, přesně
    opačně, než je zvyklost). Implementováno jako implikace pro každou
    dvojici (víkendový den, všední den): pokud je víkendový den plně
    obsazený (D i N), musí být plně obsazený i ten všední - jakmile jsou
    všechny víkendy vyčerpané (žádný není plně obsazený), všední dny jsou
    volné pro krizi jako obvykle. Na rozdíl od preferovat_krizove_o_vikendu
    výš tohle NEMĚNÍ celkový počet krizových dnů (ten určuje jen
    prioritizovat_obsazeni/fond hodin) - jen vynucuje, že se nejdřív musí
    "spotřebovat" všechny víkendy, než přijde na řadu všední den.

    prioritizovat_obsazeni: pro profil "optimalizovany" - lexikografická
    hierarchie úrovní priority (na přání, zobecněno z původního
    dvoufázového "obsazení, pak zbytek"): obsazení -> rozložení plných
    dnů (víkend/pondělí) -> férovost + neslučitelné dvojice -> zvyklosti
    (sobota=neděle, nezkušení bez dozoru). Každá úroveň se vyřeší
    SAMOSTATNĚ (bez nižších priorit v cíli), dosažené optimum se zamkne
    jako tvrdé minimum pro další úroveň - garance je strukturální (tvrdé
    pravidlo z předchozí úrovně), ne otázka poměru vah v jednom součtu.
    Zkoušelo se nejdřív jen vyšší vahy.plne_obsazeni (viz
    web/app.py:VYCHOZI_VAHY) - matematicky by měla dominovat nad
    férovostí, ale velký koeficient v jediném součtu prokazatelně ZHORŠIL
    výsledek (10 → 19 krizových dnů na reálných datech) - CP-SAT search
    heuristiky jsou citlivé na rozptyl velikostí koeficientů v cíli, ne
    jen jejich poměr. Čas se dělí rovnoměrně mezi (aktivní) úrovně,
    poslední dostane zbytek. Přesný mechanismus viz kód níž.
    """
    pocet_dni = config.pocet_dni
    dny = range(pocet_dni)  # interně 0-indexováno, navenek (config, Schedule) 1-indexováno
    lide = config.jmena
    D, N = "D", "N"
    o = config.obsazeni
    vahy = config.vahy

    model = cp_model.CpModel()

    smena = {
        (z, d, s): model.NewBoolVar(f"s_{z}_{d}_{s}")
        for z in lide
        for d in dny
        for s in (D, N)
    }

    # --- tvrdá pravidla ---

    # Max 1 směna denně na osobu
    for z in lide:
        for d in dny:
            model.AddAtMostOne(smena[z, d, D], smena[z, d, N])

    # Pevně dané směny (úkol 9: zamčené směny jako fixní vstup, ne jen
    # "nepřepisovat v DB") - vynuceny HNED na začátku, ať z nich ostatní
    # pravidla níž (N->D zákaz, max v řadě, fond) automaticky těží stejně,
    # jako by šlo o čerstvě navržený výsledek, ne dodatečnou výjimku.
    for z, dny_smeny in config.pevne_smeny.items():
        for den, typ in dny_smeny.items():
            model.Add(smena[z, den - 1, typ] == 1)

    # Obsazení směn
    for d in dny:
        model.Add(sum(smena[z, d, D] for z in lide) >= o.denni_min)
        model.Add(sum(smena[z, d, D] for z in lide) <= o.denni_max)
        model.Add(sum(smena[z, d, N] for z in lide) >= o.nocni_min)
        model.Add(sum(smena[z, d, N] for z in lide) <= o.nocni_max)

    # Po noční nesmí následovat denní další den
    for z in lide:
        for d in range(pocet_dni - 1):
            model.AddImplication(smena[z, d, N], smena[z, d + 1, D].Not())

    # Max max_v_rade směn v řadě, pak volno (individuální strop viz
    # Config.max_v_rade_override, jinak společné config.pravidla.max_v_rade)
    pracuje = {}
    for z in lide:
        for d in dny:
            p = model.NewBoolVar(f"p_{z}_{d}")
            model.Add(smena[z, d, D] + smena[z, d, N] == 1).OnlyEnforceIf(p)
            model.Add(smena[z, d, D] + smena[z, d, N] == 0).OnlyEnforceIf(p.Not())
            pracuje[z, d] = p
        max_v_rade = config.max_v_rade_override.get(z, config.pravidla.max_v_rade)
        for d in range(pocet_dni - max_v_rade):
            model.Add(sum(pracuje[z, d + i] for i in range(max_v_rade + 1)) <= max_v_rade)

    # Po 2 nočních v řadě musí následovat 2 dny volna. Tím je zároveň
    # vyloučena i 3. noční v řadě - navazovala by na dvojici, které povinné
    # volno předepisuje, takže by sama sobě odporovala.
    for z in lide:
        for d in range(pocet_dni - 1):
            dve_nocni = model.NewBoolVar(f"dve_nocni_{z}_{d}")
            model.AddBoolAnd(smena[z, d, N], smena[z, d + 1, N]).OnlyEnforceIf(dve_nocni)
            model.AddBoolOr(
                smena[z, d, N].Not(), smena[z, d + 1, N].Not()
            ).OnlyEnforceIf(dve_nocni.Not())
            if d + 2 < pocet_dni:
                model.Add(pracuje[z, d + 2] == 0).OnlyEnforceIf(dve_nocni)
            if d + 3 < pocet_dni:
                model.Add(pracuje[z, d + 3] == 0).OnlyEnforceIf(dve_nocni)

    # Nedostupnosti
    for jmeno, dny_volna in config.nedostupnosti.items():
        for den in dny_volna:
            model.Add(pracuje[jmeno, den - 1] == 0)

    # Zakázaná dvojice - na rozdíl od nekompatibilni_dvojice (měkké, viz
    # cíl níž) nesmí spolu sloužit NIKDY, ani kdyby to jinak nešlo.
    for a, b in config.zakazane_dvojice:
        for d in dny:
            for s in (D, N):
                model.AddBoolOr(smena[a, d, s].Not(), smena[b, d, s].Not())

    # Nedostupnost jen pro konkrétní typ směny (viz Config.zakazane_smeny) -
    # na rozdíl od nedostupnosti výš tu člověk zůstává k dispozici pro
    # zbylý typ směny.
    for jmeno, dny_omezeni in config.zakazane_smeny.items():
        for den, typy in dny_omezeni.items():
            for typ in typy:
                model.Add(smena[jmeno, den - 1, typ] == 0)

    # Fond pracovní doby (individuální strop viz Config.max_smen_mesic_override,
    # jinak společný config.pravidla.max_smen_mesic)
    for z in lide:
        strop = config.max_smen_mesic_override.get(z, config.pravidla.max_smen_mesic)
        model.Add(sum(pracuje[z, d] for d in dny) <= strop)

    # --- měkká pravidla (optimalizační cíl), rozdělená do úrovní priority
    # pro prioritizovat_obsazeni níž (od nejdůležitější): rozložení plných
    # dnů (které dny) -> férovost mezi lidmi + neslučitelné dvojice
    # (původní pravidla z CLAUDE.md) -> zvyklosti (nejnovější, na přání).
    plna_promenne = []  # jen plna_d/plna_n bez váhy - úroveň 0 (obsazení)
    cile_rozlozeni = []  # úroveň 1: KTERÉ dny jsou plné (víkend/pondělí)
    cile_ferovost = []  # úroveň 2: férovost + neslučitelné dvojice
    cile_zvyklosti = []  # úroveň 3: sobota=neděle, nezkušení bez dozoru
    plna_d_den: dict[int, cp_model.IntVar] = {}
    plna_n_den: dict[int, cp_model.IntVar] = {}

    for d in dny:
        vsedni_den_weekday = date(config.rok, config.mesic, d + 1).weekday()
        je_vikend_d = vsedni_den_weekday >= 5
        vaha_obsazeni = vahy.plne_obsazeni
        if preferovat_krizove_o_vikendu and not je_vikend_d:
            vaha_obsazeni *= _VIKENDOVY_FAKTOR_VSEDNI_DEN
        if vyhnout_se_pondeli and vsedni_den_weekday == 0:
            vaha_obsazeni *= _PONDELI_DALSI_FAKTOR

        plna_d = model.NewBoolVar(f"plnaD_{d}")
        model.Add(sum(smena[z, d, D] for z in lide) == o.denni_max).OnlyEnforceIf(plna_d)
        if krizove_jen_o_vikendu:
            # Obousměrná reifikace (ne jen "plna_d=True => plný") jen když
            # je potřeba (navíc omezení = navíc čas solveru) - bez ní by
            # krizove_jen_o_vikendu níž šlo obejít: solver by mohl nechat
            # plna_d=False i na skutečně plně obsazeném víkendovém dnu, jen
            # aby se vyhnul povinnosti dotáhnout na plno i všední dny.
            model.Add(sum(smena[z, d, D] for z in lide) < o.denni_max).OnlyEnforceIf(plna_d.Not())
        cile_rozlozeni.append(vaha_obsazeni * plna_d)
        plna_promenne.append(plna_d)
        plna_d_den[d] = plna_d

        plna_n = model.NewBoolVar(f"plnaN_{d}")
        model.Add(sum(smena[z, d, N] for z in lide) == o.nocni_max).OnlyEnforceIf(plna_n)
        if krizove_jen_o_vikendu:
            model.Add(sum(smena[z, d, N] for z in lide) < o.nocni_max).OnlyEnforceIf(plna_n.Not())
        cile_rozlozeni.append(vaha_obsazeni * plna_n)
        plna_promenne.append(plna_n)
        plna_n_den[d] = plna_n

    if krizove_jen_o_vikendu:
        # Krizový všední den smí nastat, jen když jsou už krizové VŠECHNY
        # víkendové dny (viz docstring výš) - pro každou dvojici (víkendový
        # den, všední den): plně obsazený víkend => musí být plně obsazený
        # i ten všední den. Jakmile ani jeden víkend není plný, implikace
        # je pro všechny dvojice splněná automaticky a všední dny jsou
        # volné jako obvykle.
        vikendove_dny = [d for d in dny if date(config.rok, config.mesic, d + 1).weekday() >= 5]
        vsedni_dny = [d for d in dny if date(config.rok, config.mesic, d + 1).weekday() < 5]
        plny_den = {}
        for d in vikendove_dny:
            p = model.NewBoolVar(f"plny_vikend_{d}")
            model.AddBoolAnd(plna_d_den[d], plna_n_den[d]).OnlyEnforceIf(p)
            model.AddBoolOr(plna_d_den[d].Not(), plna_n_den[d].Not()).OnlyEnforceIf(p.Not())
            plny_den[d] = p
        for w in vikendove_dny:
            for d in vsedni_dny:
                model.AddImplication(plny_den[w], plna_d_den[d])
                model.AddImplication(plny_den[w], plna_n_den[d])

    if preferovat_stejnou_smenu_o_vikendu:
        # Bonus za to, že sobota a neděle mají u téhož člověka STEJNÝ typ
        # (D+D, N+N nebo oba volno) - jen měkké, viz docstring výš.
        for d in dny:
            if date(config.rok, config.mesic, d + 1).weekday() == 5 and d + 1 < pocet_dni:
                for z in lide:
                    soulad = model.NewBoolVar(f"soulad_vikend_{z}_{d}")
                    model.Add(smena[z, d, D] == smena[z, d + 1, D]).OnlyEnforceIf(soulad)
                    model.Add(smena[z, d, N] == smena[z, d + 1, N]).OnlyEnforceIf(soulad)
                    cile_zvyklosti.append(_VAHA_SOULAD_VIKENDU * soulad)

    zkuseni_nezkuseni = [z for z in nezkuseni if z in lide]
    if zkuseni_nezkuseni:
        zkuseni_lide = [z for z in lide if z not in zkuseni_nezkuseni]
        for d in dny:
            for s in (D, N):
                zadny_zkuseny = model.NewBoolVar(f"zadny_zkuseny_{d}_{s}")
                # Jen jednosměrná reifikace stačí (penalizace, ne odměna) -
                # cíl chce zadny_zkuseny=False, takže bez tyhle podmínky by
                # ho tak solver nastavil "zadarmo" i když je reálně bez
                # zkušeného dozoru. Naopak False => aspoň 1 zkušený zaručuje,
                # že "False" nejde tvrdit nepravdivě.
                model.Add(sum(smena[z, d, s] for z in zkuseni_lide) >= 1).OnlyEnforceIf(
                    zadny_zkuseny.Not()
                )
                cile_zvyklosti.append(-_VAHA_NEZKUSENI_BEZ_DOZORU * zadny_zkuseny)

    nocni_pocty = [sum(smena[z, d, N] for d in dny) for z in lide]
    noc_max = model.NewIntVar(0, pocet_dni, "noc_max")
    noc_min = model.NewIntVar(0, pocet_dni, "noc_min")
    model.AddMaxEquality(noc_max, nocni_pocty)
    model.AddMinEquality(noc_min, nocni_pocty)
    cile_ferovost.append(-vahy.ferovost_nocni * (noc_max - noc_min))

    vikendy = [d for d in dny if date(config.rok, config.mesic, d + 1).weekday() >= 5]
    vik_pocty = [sum(pracuje[z, d] for d in vikendy) for z in lide]
    vik_max = model.NewIntVar(0, pocet_dni, "vik_max")
    vik_min = model.NewIntVar(0, pocet_dni, "vik_min")
    model.AddMaxEquality(vik_max, vik_pocty)
    model.AddMinEquality(vik_min, vik_pocty)
    cile_ferovost.append(-vahy.ferovost_vikendy * (vik_max - vik_min))

    celkem = [sum(pracuje[z, d] for d in dny) for z in lide]
    c_max = model.NewIntVar(0, pocet_dni, "c_max")
    c_min = model.NewIntVar(0, pocet_dni, "c_min")
    model.AddMaxEquality(c_max, celkem)
    model.AddMinEquality(c_min, celkem)
    cile_ferovost.append(-vahy.ferovost_celkem * (c_max - c_min))

    for a, b in config.nekompatibilni_dvojice:
        for d in dny:
            for s in (D, N):
                spolu = model.NewBoolVar(f"spolu_{a}_{b}_{d}_{s}")
                model.AddBoolAnd(smena[a, d, s], smena[b, d, s]).OnlyEnforceIf(spolu)
                model.AddBoolOr(
                    smena[a, d, s].Not(), smena[b, d, s].Not()
                ).OnlyEnforceIf(spolu.Not())
                cile_ferovost.append(-vahy.nekompatibilni_penalizace * spolu)

    if prioritizovat_obsazeni:
        # Lexikografická hierarchie úrovní priority (zobecnění dřívějšího
        # dvoufázového "obsazení, pak zbytek" na přání o zvyklostech):
        # každá úroveň se vyřeší SAMOSTATNĚ (bez nižších priorit v cíli),
        # její dosažené optimum se zamkne jako tvrdé minimum pro DALŠÍ
        # (nižší) úroveň, teprve pak se ta řeší. Garance je strukturální
        # (tvrdé pravidlo z předchozí úrovně), ne otázka poměru vah v
        # jednom součtu - vyšší váha samotná už jednou prokazatelně
        # zhoršila výsledek (10 → 19 krizových dnů, viz historie).
        #   0. obsazení (plna_promenne, bez váhy) - kolik dnů je plných
        #   1. rozložení + férovost + neslučitelné dvojice (spojené jako
        #      původně) - KTERÉ dny jsou plné (víkend/pondělí přednost) i
        #      mezi kým se rozdělí, řeší se SPOLU. Zkoušelo se rozdělit i
        #      tohle na dvě samostatné úrovně (rozložení jako vyšší
        #      priorita než férovost), ale na stejný celkový čas to
        #      REGRESOVALO (nález testem: samostatná úroveň "rozložení"
        #      při omezeném čase někdy nedosáhla ani stejného počtu
        #      plných dnů jako úroveň 0) - víc úrovní = míň času na
        #      každou, CP-SAT to nestíhal dohnat.
        #   2. zvyklosti (cile_zvyklosti) - sobota=neděle, nezkušení bez
        #      dozoru - jen když je aspoň jedna z těch preferencí zapnutá
        #      (nejnovější, nejnižší priorita, viz na přání)
        urovne = [plna_promenne, cile_rozlozeni + cile_ferovost]
        if cile_zvyklosti:
            urovne.append(cile_zvyklosti)

        # Úroveň 0 dostane pevně 1/3 (jako původně, ověřeno spolehlivé),
        # zbytek se rovnoměrně rozdělí mezi zbývající (1 nebo 2) úrovně -
        # beze zvyklostí je to přesně původní dvoufázové 1/3 + 2/3.
        cas_obsazeni = time_limit_s / 3
        cas_na_uroven = (time_limit_s - cas_obsazeni) / (len(urovne) - 1)

        zbyvajici_cas = time_limit_s
        for i, vyrazy in enumerate(urovne):
            je_posledni = i == len(urovne) - 1
            cas = zbyvajici_cas if je_posledni else (cas_obsazeni if i == 0 else cas_na_uroven)
            model.Maximize(sum(vyrazy))
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = cas
            if random_seed is not None:
                solver.parameters.random_seed = random_seed
                solver.parameters.num_search_workers = 1
            status = solver.Solve(model)
            if not je_posledni:
                zbyvajici_cas -= cas
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    # Tvrdé minimum pro další úroveň - tahle už nesmí
                    # klesnout pod to, co tahle úroveň prokazatelně umí,
                    # ať nižší priorita níž nemůže "ukrást" nic zpátky.
                    nejlepsi = round(solver.ObjectiveValue())
                    model.Add(sum(vyrazy) >= nejlepsi)
                    # Hint řešením týhle úrovně pro tu další - bez tohohle
                    # by další úroveň musela hledat přípustný bod ÚPLNĚ
                    # ZNOVA (jiný cíl = jiné pořadí prohledávání) a na
                    # složitějším zadání to prokazatelně nestíhala
                    # (skončila UNKNOWN, i když řešení evidentně existuje
                    # - viz test). ClearHints - jinak by se hint z týhle
                    # úrovně jen přidal k hintu z úrovně předchozí (stejná
                    # proměnná dvakrát v hint listu).
                    model.ClearHints()
                    for promenna in smena.values():
                        model.AddHint(promenna, solver.Value(promenna))
                # Nesplnitelnost (INFEASIBLE) na nižší než poslední úrovni
                # nastat nemůže - tvrdá pravidla jsou stejná jako u jediné
                # fáze. Nedostatek času (UNKNOWN) se prostě přeskočí beze
                # zamčení/hintu, diagnostika běží až po poslední úrovni.
    else:
        model.Maximize(sum(cile_rozlozeni + cile_ferovost + cile_zvyklosti))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        if random_seed is not None:
            solver.parameters.random_seed = random_seed
            # Determinismus (stejný seed -> stejný výsledek) vyžaduje
            # jediné vlákno - výchozí paralelní portfolio search seed
            # nerespektuje.
            solver.parameters.num_search_workers = 1
        status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        duvody = _diagnostikuj_nesplnitelnost(config)
        if not duvody:
            duvody = [
                "Solver nenašel žádné řešení, ale automatická diagnostika "
                "nenašla zjevnou příčinu — zkontrolujte ručně kombinaci "
                "nedostupností, max_v_rade a obsazení."
            ]
        raise NelzeSestavitError(duvody)

    smeny_out: dict[tuple[str, int], str] = {}
    for z in lide:
        for d in dny:
            ma_denni = solver.Value(smena[z, d, D])
            ma_nocni = solver.Value(smena[z, d, N])
            assert not (ma_denni and ma_nocni), f"{z} má den {d + 1} obě směny naráz"
            if ma_denni:
                smeny_out[z, d + 1] = "D"
            elif ma_nocni:
                smeny_out[z, d + 1] = "N"

    duvody_out = {
        (jmeno, den): duvod
        for jmeno, dny_duvodu in config.duvody_nedostupnosti.items()
        for den, duvod in dny_duvodu.items()
    }

    return Schedule(
        rok=config.rok,
        mesic=config.mesic,
        jmena=lide,
        smeny=smeny_out,
        status=solver.StatusName(status),
        cas_reseni=solver.WallTime(),
        duvody_nedostupnosti=duvody_out,
    )
