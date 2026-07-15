#!/usr/bin/env python3
"""
Generátor měsíčního rozpisu služeb - nepřetržitý provoz, 12h směny.
Prototyp: OR-Tools CP-SAT solver.

Pravidla (tvrdá):
- Denní směna: 3-4 lidi, noční: 1-2 lidi
- Po noční nesmí následovat denní (N->D zakázáno, N->N povoleno)
- Max 3 pracovní dny v řadě, pak min 1 den volna
- Max 1 směna za den na osobu
- Respektování požadavků na volno (dovolená, soukromé)
- Max směn na osobu za měsíc (fond pracovní doby)

Optimalizace (měkká, dle priority):
1. Co nejvíc dní s plným obsazením (4 denní, 2 noční)
2. Spravedlivé rozdělení nočních směn
3. Spravedlivé rozdělení víkendových směn
4. Vyrovnaný celkový počet směn
"""

from ortools.sat.python import cp_model
import calendar
from datetime import date

# ====================== KONFIGURACE ======================

ROK = 2026
MESIC = 8  # srpen jako příklad

ZAMESTNANCI = [
    "Alena", "Bedřich", "Cyril", "Dana", "Emil", "Františka",
    "Gustav", "Hana", "Ivan", "Jitka", "Karel", "Lenka",
]

MAX_SMEN_MESIC = 15       # fond: ~37,5 h/týden -> ~15x12h směn
MAX_V_RADE = 3            # max směn po sobě, pak volno
DENNI_MIN, DENNI_OPT = 3, 4
NOCNI_MIN, NOCNI_OPT = 2, 2

# Požadavky na volno: jméno -> seznam dní v měsíci
MUZI = ["Cyril", "Karel"]  # fyzicka vypomoc - nemeli by slouzit spolu (mekke)

POZADAVKY_VOLNO = {
    "Alena": list(range(3, 10)),      # dovolená 3.-9.
    "Dana": [14, 15],                  # soukromé
    "Gustav": list(range(20, 27)),     # dovolená 20.-26.
    "Jitka": [1, 2],
    "Karel": [28, 29, 30],
}

# ==========================================================

POCET_DNI = calendar.monthrange(ROK, MESIC)[1]
DNY = range(POCET_DNI)
LIDE = range(len(ZAMESTNANCI))
D, N = 0, 1  # denní, noční

model = cp_model.CpModel()

# smena[z][d][s] = 1, pokud zaměstnanec z má den d směnu s
smena = {}
for z in LIDE:
    for d in DNY:
        for s in (D, N):
            smena[z, d, s] = model.NewBoolVar(f"s_{z}_{d}_{s}")

# --- Tvrdá pravidla ---

# Max 1 směna denně na osobu
for z in LIDE:
    for d in DNY:
        model.AddAtMostOne(smena[z, d, D], smena[z, d, N])

# Obsazení směn (min a max)
for d in DNY:
    model.Add(sum(smena[z, d, D] for z in LIDE) >= DENNI_MIN)
    model.Add(sum(smena[z, d, D] for z in LIDE) <= DENNI_OPT)
    model.Add(sum(smena[z, d, N] for z in LIDE) >= NOCNI_MIN)
    model.Add(sum(smena[z, d, N] for z in LIDE) <= NOCNI_OPT)

# Po noční nesmí následovat denní další den (N konči ráno)
for z in LIDE:
    for d in range(POCET_DNI - 1):
        model.AddImplication(smena[z, d, N], smena[z, d + 1, D].Not())

# Max 3 pracovní dny v řadě (v každém okně 4 dní max 3 směny)
pracuje = {}
for z in LIDE:
    for d in DNY:
        p = model.NewBoolVar(f"p_{z}_{d}")
        model.Add(smena[z, d, D] + smena[z, d, N] == 1).OnlyEnforceIf(p)
        model.Add(smena[z, d, D] + smena[z, d, N] == 0).OnlyEnforceIf(p.Not())
        pracuje[z, d] = p
    for d in range(POCET_DNI - MAX_V_RADE):
        model.Add(sum(pracuje[z, d + i] for i in range(MAX_V_RADE + 1)) <= MAX_V_RADE)

# Požadavky na volno
for jmeno, dny_volna in POZADAVKY_VOLNO.items():
    z = ZAMESTNANCI.index(jmeno)
    for den in dny_volna:
        model.Add(pracuje[z, den - 1] == 0)

# Fond pracovní doby
for z in LIDE:
    model.Add(sum(pracuje[z, d] for d in DNY) <= MAX_SMEN_MESIC)

# --- Měkká pravidla (optimalizace) ---

cile = []

# 1. Preferovat plné obsazení (4 denní, 2 noční) - váha 10
for d in DNY:
    plna_d = model.NewBoolVar(f"plnaD_{d}")
    model.Add(sum(smena[z, d, D] for z in LIDE) == DENNI_OPT).OnlyEnforceIf(plna_d)
    cile.append(10 * plna_d)
    plna_n = model.NewBoolVar(f"plnaN_{d}")
    model.Add(sum(smena[z, d, N] for z in LIDE) == NOCNI_OPT).OnlyEnforceIf(plna_n)
    cile.append(10 * plna_n)

# 2. Férovost nočních: minimalizovat rozdíl max-min počtu nočních
nocni_pocty = [sum(smena[z, d, N] for d in DNY) for z in LIDE]
noc_max = model.NewIntVar(0, POCET_DNI, "noc_max")
noc_min = model.NewIntVar(0, POCET_DNI, "noc_min")
model.AddMaxEquality(noc_max, nocni_pocty)
model.AddMinEquality(noc_min, nocni_pocty)
cile.append(-5 * (noc_max - noc_min))

# 3. Férovost víkendů
vikendy = [d for d in DNY if date(ROK, MESIC, d + 1).weekday() >= 5]
vik_pocty = [sum(pracuje[z, d] for d in vikendy) for z in LIDE]
vik_max = model.NewIntVar(0, POCET_DNI, "vik_max")
vik_min = model.NewIntVar(0, POCET_DNI, "vik_min")
model.AddMaxEquality(vik_max, vik_pocty)
model.AddMinEquality(vik_min, vik_pocty)
cile.append(-3 * (vik_max - vik_min))

# 4. Vyrovnaný celkový počet směn
celkem = [sum(pracuje[z, d] for d in DNY) for z in LIDE]
c_max = model.NewIntVar(0, POCET_DNI, "c_max")
c_min = model.NewIntVar(0, POCET_DNI, "c_min")
model.AddMaxEquality(c_max, celkem)
model.AddMinEquality(c_min, celkem)
cile.append(-4 * (c_max - c_min))


# 5. Rozprostreni muzu: penalizace, kdyz oba slouzi stejnou smenu tyz den
muzi_idx = [ZAMESTNANCI.index(j) for j in MUZI]
if len(muzi_idx) == 2:
    a, b = muzi_idx
    for d in DNY:
        for s in (D, N):
            spolu = model.NewBoolVar(f"spolu_{d}_{s}")
            model.AddBoolAnd(smena[a, d, s], smena[b, d, s]).OnlyEnforceIf(spolu)
            model.AddBoolOr(smena[a, d, s].Not(), smena[b, d, s].Not()).OnlyEnforceIf(spolu.Not())
            cile.append(-8 * spolu)

model.Maximize(sum(cile))

# --- Řešení ---
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 30
status = solver.Solve(model)

if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    print("NELZE SESTAVIT ROZPIS - podmínky jsou nesplnitelné.")
    print("Zkontrolujte požadavky na volno vs. minimální obsazení.")
    raise SystemExit(1)

# --- Výpis ---
CZ_DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

print(f"ROZPIS SLUŽEB {MESIC}/{ROK}  (řešení: {solver.StatusName(status)}, {solver.WallTime():.1f}s)")
print()

# Hlavička
jmena_kratka = [j[:4] for j in ZAMESTNANCI]
print("Den        " + " ".join(f"{j:>4}" for j in jmena_kratka) + "   Denní Noční")
print("-" * (11 + 5 * len(ZAMESTNANCI) + 14))

for d in DNY:
    datum = date(ROK, MESIC, d + 1)
    wd = CZ_DNY[datum.weekday()]
    znacka = "*" if datum.weekday() >= 5 else " "
    radek = f"{d+1:2}. {wd}{znacka}    "
    pocet_d = pocet_n = 0
    for z in LIDE:
        if solver.Value(smena[z, d, D]):
            radek += "   D "
            pocet_d += 1
        elif solver.Value(smena[z, d, N]):
            radek += "   N "
            pocet_n += 1
        else:
            jmeno = ZAMESTNANCI[z]
            if jmeno in POZADAVKY_VOLNO and (d + 1) in POZADAVKY_VOLNO[jmeno]:
                radek += "   x "  # požadované volno
            else:
                radek += "   . "
    varovani = "  !" if (pocet_d < DENNI_OPT or pocet_n < NOCNI_OPT) else ""
    radek += f"    {pocet_d}     {pocet_n}{varovani}"
    print(radek)

print()
print("D=denní  N=noční  x=požadované volno  .=volno  *=víkend  !=podstav")
print()
print("Souhrn na osobu:")
print(f"{'Jméno':<12} {'Směn':>4} {'Hodin':>5} {'Nočních':>7} {'Víkend':>6}")
for z in LIDE:
    n_smen = sum(solver.Value(pracuje[z, d]) for d in DNY)
    n_noc = sum(solver.Value(smena[z, d, N]) for d in DNY)
    n_vik = sum(solver.Value(pracuje[z, d]) for d in vikendy)
    print(f"{ZAMESTNANCI[z]:<12} {n_smen:>4} {n_smen*12:>5} {n_noc:>7} {n_vik:>6}")
