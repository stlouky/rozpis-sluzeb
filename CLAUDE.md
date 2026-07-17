# Rozpis služeb — generátor směn pro nepřetržitý provoz

## Co to je
Webová appka generující měsíční rozpis 12h směn pro domov důchodců (~12 zaměstnanců).
Nahrazuje ruční plánování. Evidenci hodin a mzdy řeší externí systém (Cygnus) —
my děláme JEN návrh rozpisu a jeho přeskládání při změnách.
Kompletní návrh viz NAVRH.md.

## Stack
Python 3.13, OR-Tools CP-SAT (solver), FastAPI, SQLite, Jinja2.
Deploy: Hetzner VPS, systemd + Caddy. Žádný frontend build systém.
Python 3.13+, běh a testy VŽDY přes .venv (.venv/bin/python -m pytest)
— systémový Python nemá ortools/pyyaml. Na deploy cílit Python 3.13
(verze na produkčním serveru, Debian 13 - viz DEPLOY.md, úkol 0b).

## Doménová pravidla (NEMĚNIT bez zadání)

Tvrdá:
- denní směna (D): 3–4 lidi, noční (N): tvrdě 1–2; normální profil vyžaduje 2,
  krizový profil povolí 1 — platí každý den vč. víkendů a svátků
- po noční NESMÍ následovat denní další den (N→D zakázáno, N→N ok)
- max 2 noční v řadě, po nich povinně 2 dny volna (3 noční za sebou zakázáno)
- max 3 směny v řadě, pak min 1 den volna
- max 1 směna na osobu a den
- respektovat nedostupnosti (DOV/NEM/OST/požadavky)
- max ~15 směn na osobu za měsíc

Měkká (optimalizace, s vahami):
- preferovat plné obsazení 4+2 (váha 10)
- neslučitelná dvojice: označení zaměstnanci (fyzická výpomoc) spolu slouží
  JEN když to jinak nejde (penalizace 8, konfigurovatelné)
- férové rozdělení nočních (5), víkendů (3) a celkových směn (4)
  — víkendy jsou lépe placené, férovost hlídá obě strany

## Klíčové workflow
Požadavky na volno chodí i v průběhu měsíce. Změna = zamknout minulost
a odpracované směny, přegenerovat jen zbytek měsíce, ukázat diff.

## Konvence
- komentáře, UI i kód (názvy proměnných/tříd/funkcí) česky — konzistentně s prototypem
- jeden task = jeden commit
- solver vždy s time limitem (max_time_in_seconds)
- při nesplnitelnosti VŽDY vypsat proč (které dny/pravidla kolidují)

## Stav
- [x] prototyp solveru (archiv/rozpis.py) — funkční, pravidla ověřena
- [x] fáze 1: modul + YAML konfigurace + testy
- [x] fáze 2: SQLite (db/) + správa zaměstnanců a nedostupností + most na solver
- [x] fáze 5: PDF (A4 šířka, nástěnka) — vystup/pdf.py hotový vč. testů
- [ ] fáze 3: FastAPI + login + barevná mřížka (žlutá D, modrá N, zelená DOV)
- [ ] fáze 4: zamykání + přegenerování + diff
- [ ] fáze 6: deploy (Hetzner, systemd + Caddy)
