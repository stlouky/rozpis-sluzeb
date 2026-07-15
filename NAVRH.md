# Rozpis služeb — návrh aplikace (v2)

Generátor měsíčního rozpisu služeb pro nepřetržitý provoz (12h směny).
Běží na VPS (Hetzner), přístup přes web odkudkoliv.

**Scope:** appka GENERUJE NÁVRH rozpisu. Evidenci hodin, fondy a mzdy řeší
Cygnus — my nahrazujeme jen tu ruční, časově náročnou část: sestavení plánu
políčko po políčku a jeho přeskládávání při každé změně.

## Stack

- Python 3.12, FastAPI, OR-Tools (CP-SAT), SQLite
- Frontend: Jinja2 + trocha JS (mřížka s barvami jako v Cygnusu:
  žlutá=denní, modrá=noční, zelená=dovolená — vedoucí to už zná)
- Výstup: PDF na nástěnku (A4 šířka), XLSX, případně obrazovka pro přepis do Cygnusu
- Deploy: systemd + Caddy (HTTPS), zálohy = kopie SQLite souboru

## Datový model

```
employee          id, jméno, aktivní, štítky (např. "fyzická výpomoc")
unavailability    employee_id, od, do, typ (DOV/NEM/OST/ŠvZ/požadavek), poznámka
shift             employee_id, datum, typ (D/N), locked, stav
pair_rule         employee_a, employee_b, typ (nesmí spolu / rozprostřít)
settings          obsazení, max v řadě, váhy férovosti...
```

Pozn.: DOV/NEM/OST/ŠvZ jsou pro nás jen NEDOSTUPNOSTI (vstup pro solver).
Jejich hodinové ocenění řeší Cygnus.

## Pravidla

### Tvrdá
- denní 3–4, noční 1–2 (konfigurovatelné; ověřit reálná minima, možná jiná o víkendu)
- zákaz N→D následující den (odpočinek)
- max 3 směny v řadě, pak volno
- nedostupnosti (dovolená, nemoc, schválené požadavky)
- **neslučitelné dvojice:** např. 2 muži na fyzickou výpomoc NESMÍ sloužit
  na stejné směně — musí být rozprostřeni
  (volitelně měkce: ideálně 1 z dvojice na každé denní směně)

### Měkká (optimalizace s vahami)
- preferovat plné obsazení (4+2)
- férové rozdělení víkendů — víkendy jsou lépe placené, takže férovost
  funguje OBĚMA směry (nikdo nesmí být zvýhodněn ani ochuzen)
- férové rozdělení nočních
- vyrovnaný počet směn za měsíc
- (fáze 2) osobní preference typu "raději noční"

## Klíčové workflow: změny v průběhu měsíce

Požadavky chodí průběžně → tohle musí být bleskové:

1. vedoucí zadá novou nedostupnost (nemoc od 12., požadavek na 20.)
2. minulost a odpracované směny se automaticky ZAMKNOU
3. volitelně zamkne i budoucí směny, které nechce hýbat
4. solver přegeneruje jen zbytek měsíce
5. DIFF náhled: "co se komu mění" → potvrdit → hotovo, tisk

Cíl: změna, která dnes zabere hodinu přeskládávání, na 2 minuty.

## Funkce podle priorit

| Fáze | Obsah |
|------|-------|
| 1 | solver: pravidla vč. neslučitelných dvojic + testy |
| 2 | DB + správa zaměstnanců a nedostupností (jednoduchý formulář) |
| 3 | generování + barevná mřížka + ruční úpravy s validací |
| 4 | zamykání + přegenerování zbytku měsíce + diff |
| 5 | PDF/XLSX výstup |
| 6 | login vedoucí, deploy Hetzner |
| 7 | (volitelně) přístup zaměstnanců: zadávání požadavků, "moje směny" |

## Otevřené otázky pro kamarádku

1. Skutečná minima obsazení — liší se všední den × víkend × svátek?
2. Existují další vazby mezi lidmi (kdo nesmí/měl by s kým)?
3. Chodí požadavky písemně, nebo ústně? (→ jestli má smysl fáze 7)
4. Kolik lidí z papíru je kmenových vs. výpomoc?
