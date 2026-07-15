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
        min(config.pravidla.max_smen_mesic, pocet_dni - len(nedostupny.get(jmeno, set())))
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


def generate_schedule(config: Config, time_limit_s: float = 30.0) -> Schedule:
    """Vygeneruje rozpis pro daný config.

    Vyhazuje NelzeSestavitError, pokud zadání nemá přípustné řešení.
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

    # Max max_v_rade směn v řadě, pak volno
    pracuje = {}
    for z in lide:
        for d in dny:
            p = model.NewBoolVar(f"p_{z}_{d}")
            model.Add(smena[z, d, D] + smena[z, d, N] == 1).OnlyEnforceIf(p)
            model.Add(smena[z, d, D] + smena[z, d, N] == 0).OnlyEnforceIf(p.Not())
            pracuje[z, d] = p
        max_v_rade = config.pravidla.max_v_rade
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

    # Fond pracovní doby
    for z in lide:
        model.Add(sum(pracuje[z, d] for d in dny) <= config.pravidla.max_smen_mesic)

    # --- měkká pravidla (optimalizační cíl) ---
    cile = []

    for d in dny:
        plna_d = model.NewBoolVar(f"plnaD_{d}")
        model.Add(sum(smena[z, d, D] for z in lide) == o.denni_max).OnlyEnforceIf(plna_d)
        cile.append(vahy.plne_obsazeni * plna_d)
        plna_n = model.NewBoolVar(f"plnaN_{d}")
        model.Add(sum(smena[z, d, N] for z in lide) == o.nocni_max).OnlyEnforceIf(plna_n)
        cile.append(vahy.plne_obsazeni * plna_n)

    nocni_pocty = [sum(smena[z, d, N] for d in dny) for z in lide]
    noc_max = model.NewIntVar(0, pocet_dni, "noc_max")
    noc_min = model.NewIntVar(0, pocet_dni, "noc_min")
    model.AddMaxEquality(noc_max, nocni_pocty)
    model.AddMinEquality(noc_min, nocni_pocty)
    cile.append(-vahy.ferovost_nocni * (noc_max - noc_min))

    vikendy = [d for d in dny if date(config.rok, config.mesic, d + 1).weekday() >= 5]
    vik_pocty = [sum(pracuje[z, d] for d in vikendy) for z in lide]
    vik_max = model.NewIntVar(0, pocet_dni, "vik_max")
    vik_min = model.NewIntVar(0, pocet_dni, "vik_min")
    model.AddMaxEquality(vik_max, vik_pocty)
    model.AddMinEquality(vik_min, vik_pocty)
    cile.append(-vahy.ferovost_vikendy * (vik_max - vik_min))

    celkem = [sum(pracuje[z, d] for d in dny) for z in lide]
    c_max = model.NewIntVar(0, pocet_dni, "c_max")
    c_min = model.NewIntVar(0, pocet_dni, "c_min")
    model.AddMaxEquality(c_max, celkem)
    model.AddMinEquality(c_min, celkem)
    cile.append(-vahy.ferovost_celkem * (c_max - c_min))

    for a, b in config.nekompatibilni_dvojice:
        for d in dny:
            for s in (D, N):
                spolu = model.NewBoolVar(f"spolu_{a}_{b}_{d}_{s}")
                model.AddBoolAnd(smena[a, d, s], smena[b, d, s]).OnlyEnforceIf(spolu)
                model.AddBoolOr(
                    smena[a, d, s].Not(), smena[b, d, s].Not()
                ).OnlyEnforceIf(spolu.Not())
                cile.append(-vahy.nekompatibilni_penalizace * spolu)

    model.Maximize(sum(cile))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
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
