# Stav práce — fáze 3 (webové rozhraní)

Průběžný zápis pro navázání po `/clear` nebo v nové relaci. Úkoly a jejich
přesné zadání viz `zadani-faze3-web.md` — tenhle soubor jen zaznamenává,
co už je hotovo, co zbývá a na co si dát pozor. Aktualizováno 17.7.2026.

## Pauza zrušena (17.7.2026)

Práce byla od 17.7.2026 pozastavená kvůli vyjádření kamarádky
(spoluautorka/konzultantka projektu, viz `NAVRH.md` "Otevřené otázky pro
kamarádku"), jestli má vůbec smysl appku dál budovat. Uživatel se
rozhodl na odpověď nečekat — další úpravy budou stejně jen kosmetické,
nemá smysl kvůli tomu blokovat práci. Pokračuje se normálně, na
vyžádání jako obvykle (další na řadě je Úkol 4).

## Hotovo (commitnuto na `main`)

| Úkol | Commit | Co |
|---|---|---|
| 0 | `48b3b59` | CLAUDE.md sladěno se zadáním, `rozpis.py` → `archiv/`, web závislosti do requirements.txt |
| — | `e3dbea8` | oprava kolísajícího testu solveru (nedeterminismus, ne time limit) |
| 0b | `97e87c0`, `4776272` | přechod na Python 3.13 (produkční server nemá 3.12), `.venv` přes `uv` |
| 1 | `92a60b7` | kostra webu (FastAPI+Jinja2), login/logout, `uzivatel` tabulka, server-side session, CLI `vytvorit-uzivatele`/`zmenit-heslo` |
| 2 | `6fa20bf`, `c6a5156` | `db/repository.py`: `ulozit_rozpis`, `smeny_v_mesici`, `zamknout_smeny`/`odemknout_smeny`, `smazat_nezamcene_v_obdobi`; `ulozit_rozpis` je atomická transakce a vrací `PreskocenaSmena` konflikty se zamčenými směnami |
| 3 | `a24d525` | `GET /rozpis?mesic=YYYY-MM` — mřížka měsíce, role `nahled` vidí jen aktuální měsíc, barvy podle PDF, poznámka jen pro admina, souhrn D/N/víkend (sdíleno se `Schedule`, ne duplicitní logika) |
| — | `216a5ee` | CLI `import-txt` — hromadný import z `zamestnanci.txt`/`pozadavky.txt`, idempotentní, plná podpora `zakazana_smena` |
| — | `f32f4f4` | oprava: web a CLI měly nezávislé výchozí cesty k DB → `db/cesta.py` jako jediný zdroj pravdy, web při startu ověří schéma (`overit_databazi`) |
| — | `df949f8` | oprava: `generuj` nikdy neukládal do DB → napojeno na `ulozit_rozpis`; responzivní mřížka; bonus řádek "Obsazení" v patičce |
| — | `59e8a3b` | `generuj` vypisuje souhrn vstupů (počet zaměstnanců/nedostupností) před solverem — pojistka proti generování s prázdnou DB |
| — | `33a79af` | oprava: buňka `POZADAVEK` přetékala mimo mřížku → zkráceno na `POZ` + CSS `overflow:hidden` pojistka |
| — | `0ddc25e` | `import-txt` rozpozná "končí/skončí/ukončení/odchod" → `deaktivovat_zamestnance`, ne nedostupnost; mřížka: zkratky malými písmeny |
| — | `8853deb` | `import-txt`: nerozpoznaný typ nepřítomnosti je teď chyba (SystemExit), ne tichý odhad OST |
| — | `380d8dc` | `zamestnanec.zakaz_smeny` + `zamestnanec.max_za_sebou` — trvalá osobní omezení (na rozdíl od časově ohraničené `nedostupnost.zakazana_smena`); migrace přes `ALTER TABLE ADD COLUMN` (SQLite 3.25+ podporuje CHECK bez přetvoření tabulky) |
| — | `21ec5b4` | `import-txt` rozpozná "nemoc"/"nemocná" → NEM; mřížka: NEM vlastní pastelová barva (`--barva-nem`) |
| — | `a6be3f2` | oprava: nedostupnost se v mřížce neořezávala podle `aktivni_od`/`aktivni_do` → staré záznamy "svítily" i po odchodu; DOV/NEM bez textu v buňce (jen barva); ost/poz text -30 %; krizové dny (pod měsíčním maximem obsazení) červeně tučně v řádku Obsazení |
| — | `ca5864b` | oprava (audit appky): krizové dny podle denní I noční směny, ne jen denní - noční podstav se dřív schoval za plný denní stav |
| — | `ffd67a6` | oprava (audit appky): rate limiting na `/login` (5 pokusů / 5 minut podle jména, ne IP) |
| 4 | `1acbe16` | admin: správa zaměstnanců - seznam (jen aktivní/i bývalí), přidání vč. štítku fyzická výpomoc a neslučitelných dvojic v jednom formuláři, oprava jména, deaktivace, tvrdé smazání jen bez existující směny |
| 5 | `24efadf` | admin: nedostupnosti (CRUD vč. editace, překryvy jen jako varování) + parametry pravidel (`nastaveni` tabulka, profily normalni/krizovy, `config_pro_mesic` je bere z DB místo config.yaml, pokud existují) + migrace `nedostupnost.typ` o `SVZ` (školení v zařízení) - migrace na `data/rozpis.db` provedena, viz sekce níž |
| — | `f35f553` | migrace na `data/rozpis.db` provedena (SVZ CHECK + tabulka `nastaveni`), `.gitignore` o `*.bak` |
| — | `af421f8` | oprava (audit appky): 4 nálezy (validace `od<=do` u nedostupností, doménová minima v `nastaveni`, skloňování v hlášce o překryvu, validace `aktivni_do>=aktivni_od` při deaktivaci) |
| 6 | `1729666` | admin: VYGENEROVAT - tlačítko na mřížce (měsíc + profil normalni/krizovy) → solver → uložení → potvrzení na mřížce; vždy pevný `random_seed` (num_search_workers=1, deterministické); nesplnitelnost se ukáže na mřížce s diagnostikou + "Zkusit krizový profil", HTTP 200 ne 500 |

**Testy:** 261, celá sada zelená. Spouštět vždy
`.venv/bin/python -m pytest -q` (běží ~3–4 min kvůli solver testům).

## Reálný stav dat (`data/rozpis.db`, srpen 2026)

Po posledním `import-txt` + ručních úpravách (`data/rozpis.db` je
gitignorovaná, neexistuje v gitu):

- **Černá Zdeňka** (72 let): `max_smen_mesic=10`, `zakaz_smeny='N'`,
  `max_za_sebou=1` — nikdy noční, nikdy dva dny v řadě.
- **Giňová Andrea**: brigáda skončila `aktivni_do=2026-08-16`.
- **Michnová Monika**: zkušební doba skončila `aktivni_do=2026-08-16`.
- **Bodnárová Adriana**: nemocná celý srpen (`NEM`, 1.–31.8., 0 směn).
- Poslední `generuj 2026 8`: **OPTIMAL**, ale **7 krizových dnů**
  (11., 18., 20., 22., 23., 25., 28. — jen 3D místo 4D).

### Diagnostika krizových dnů (proč a co by pomohlo)

Ověřeno natvrdo (denní obsazení vynuceno na min=max=4, ne jen
preferovaně): **0 krizových dnů momentálně NENÍ dosažitelné** se
současnými vstupy — solver nenajde řešení ani na 30 s.

Systematicky vyzkoušeno, co by pomohlo:
- Zrušení/zkrácení dovolené Stloukala (6 variant) → **nepomůže nic z toho**.
- Zrušení `max_v_rade=1` u Černé (zákaz N by zůstal) → **nepomůže**.
- Zrušení individuálního stropu 10 u Černé → **nepomůže**.
- **Zrušení nemoci Bodnárové → POMÁHÁ** (FEASIBLE) — to je jediná
  identifikovaná páka. Celková kapacita je jinak jen těsně nad potřebou
  (190 vs. 186 slotů), ale rezerva se nedá rozprostřít přes kritické
  dny 17.–24.8. (souběh nepřítomnosti víc lidí najednou).

## Rozdělané / nezačaté úkoly

- **Úkol 7** — pohled pro přepis do Cygnusu — DALŠÍ NA ŘADĚ, nezačato.
- Úkoly 8–9 — nezačato.
- Úkol 9b — samoobslužné podávání požadavků (zapsáno v
  `zadani-faze3-web.md`, revize dřívějšího "NEIMPLEMENTUJE SE") — nezačato.
- Úkol 10 (deploy) — připraveno v `DEPLOY.md` (lokální, negitované),
  čeká na úkoly 1–9(b) hotové lokálně.

## ✅ Migrace na `data/rozpis.db` provedena (17.7.2026)

Úkol 5 změnil `db/schema.sql` dvakrát: `nedostupnost.typ` CHECK rozšířen
o `SVZ` (vyžaduje přetvoření tabulky, ne ADD COLUMN) a přibyla nová
tabulka `nastaveni`. `inicializovat_schema()` se spustí JEN při založení
nového DB souboru (viz `pripojit_a_inicializovat`) — na existující
`data/rozpis.db` se žádná změna schématu neprojevila sama, proto se
ručně spustilo (SQL níž, přesně jak zapsáno) — ověřeno: `PRAGMA
integrity_check`/`foreign_key_check` OK, počet řádků `nedostupnost`
před/po sedí (19/19), `overit_databazi` i `db.cli seznam-zamestnancu`
proti reálné DB projdou. Záloha před migrací:
`data/rozpis.db.pred-migraci-svz-nastaveni.bak` (gitignorovaná stejně
jako `data/rozpis.db`). `nastaveni` je zatím prázdná (žádný profil
neuložen) - generování dál padá na `config.yaml`, dokud admin profil
poprvé neuloží přes `/admin/nastaveni`.

Použité SQL (pro referenci/další prostředí, např. produkční server po
úkolu 10):

```sql
-- 1) nedostupnost.typ: přidat SVZ do CHECK (přetvoření tabulky)
ALTER TABLE nedostupnost RENAME TO nedostupnost_stara;
CREATE TABLE nedostupnost (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zamestnanec_id INTEGER NOT NULL REFERENCES zamestnanec(id),
    od TEXT NOT NULL,
    do TEXT NOT NULL,
    typ TEXT NOT NULL CHECK (typ IN ('DOV', 'NEM', 'OST', 'SVZ', 'POZADAVEK')),
    poznamka TEXT,
    zakazana_smena TEXT CHECK (zakazana_smena IN ('D', 'N'))
);
INSERT INTO nedostupnost SELECT * FROM nedostupnost_stara;
DROP TABLE nedostupnost_stara;

-- 2) nová tabulka nastaveni
CREATE TABLE IF NOT EXISTS nastaveni (
    profil TEXT PRIMARY KEY CHECK (profil IN ('normalni', 'krizovy')),
    denni_min INTEGER NOT NULL,
    denni_max INTEGER NOT NULL,
    nocni_min INTEGER NOT NULL,
    nocni_max INTEGER NOT NULL,
    max_v_rade INTEGER NOT NULL,
    max_smen_mesic INTEGER NOT NULL,
    plne_obsazeni INTEGER NOT NULL DEFAULT 10,
    ferovost_nocni INTEGER NOT NULL DEFAULT 5,
    ferovost_vikendy INTEGER NOT NULL DEFAULT 3,
    ferovost_celkem INTEGER NOT NULL DEFAULT 4,
    nekompatibilni_penalizace INTEGER NOT NULL DEFAULT 8
);
```

Poznámka k designu (pro budoucí podobná prostředí, např. produkční
server po úkolu 10, kde se totéž bude muset spustit znovu): `nastaveni`
je v `web/db.py:OCEKAVANE_TABULKY` (konzistentně s tím, jak
`overit_databazi` chytá přesně tenhle druh nesouladu, viz její
docstring/incident) - web na nemigrované DB vůbec nenaběhne, spadne hned
při startu se srozumitelnou chybou "chybí tabulky: nastaveni", ne až
uprostřed provozu. CLI (`db/cli.py`) `overit_databazi` nevolá (nikdy
nevolalo, ani pro `uzivatel` z úkolu 1) - `generuj` proti nemigrované DB
by proběhlo v pohodě i tak: `repo.nastaveni_pro_profil` chytá
`OperationalError` "no such table" a chová se stejně, jako by tabulka
existovala, ale řádek pro daný profil v ní nebyl (fallback na
`config.yaml`, viz `db/bridge.py`). `import-txt`/`pridat-nedostupnost`
se SVZ by ale spadlo na syrový `sqlite3.IntegrityError` (CHECK na starém
`nedostupnost.typ`) - tohle ošetřené není, proto se migrace spustila
rovnou, ne až při prvním selhání. Vzor stejný jako u
`zakaz_smeny`/`max_za_sebou` (úkol 4 příprava) - "ověřeno na kopii DB
předem" než na ostrá data.

## Na co si dát pozor příště

- **`data/rozpis.db`** je aktuální reálná DB — používat ji, ne kořenové
  `rozpis.db`/`rozpis_ginova_cely_mesic.db` (osiřelé, starší schéma).
- **Živý web server (uvicorn) potřebuje restart** po každé sadě změn v
  tomhle sezení — Python moduly (`web/mrizka.py` apod.) se za běhu bez
  `--reload` nenačtou znovu. Aspoň jednou se stalo, že uživatel viděl
  starý vzhled mřížky, protože server neběžel s aktuálním kódem.
- **`web/db.py:overit_databazi`** loguje přes `logging` (INFO), nemusí
  se zobrazit ve výchozím uvicorn log configu (řešit u úkolu 10).
- **DEPLOY.md** je gitignorovaný — jen lokálně, nekopírovat do commitů.
- Solver testy jsou pomalé (~3–4 min na celou sadu) — při rychlé iteraci
  spouštět jen relevantní soubor, plnou sadu před commitem.

## Zavedené konvence z průběhu (nejsou v zadání explicitně, ale ustálily se)

- Sdílená logika mezi PDF a webem (a budoucím přepisem, úkol 7) jde přes
  `Schedule` (`solver/schedule.py`) — `db.bridge.schedule_z_db()`
  sestaví `Schedule` z uložených dat v DB stejně, jako `generate_schedule`
  vrací `Schedule` ze solveru. Nová logika zobrazení patří sem, ne jako
  kopie do `web/`.
- Výchozí cesta k DB: vždy přes `db.cesta.vychozi_cesta_db()`
  (`ROZPIS_DB` env, jinak `data/rozpis.db`) — nikdy vlastní konstanta.
- `jeden task = jeden commit` se v praxi rozšířilo i na samostatné
  opravy nalezené ručním testováním mezi úkoly — každý nález vlastní
  commit, ne squashnuto do dalšího úkolu.
- Trvalá osobní omezení (zakaz_smeny, max_za_sebou) na `zamestnanec` se
  promítají do STÁVAJÍCÍCH solver mechanismů (`zakazane_smeny`,
  `max_v_rade_override`), ne jako nová logika — vzor i pro budoucí
  podobná rozšíření.
- Diagnostika neproveditelnosti: `dataclasses.replace()` na `Config` z
  `config_pro_mesic()` pro rychlé "co kdyby" scénáře bez zásahu do DB
  (viz krizové dny výš) - užitečný postup i příště.
