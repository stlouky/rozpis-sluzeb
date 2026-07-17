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
| 7 | `23ebbce` | pohled pro přepis do Cygnusu (`/rozpis/prepis`) - seznam po zaměstnancích, jen dny s čím přepsat, velké písmo, klikací odškrtávání (jen vizuální); `/rozpis/pdf` - tenká route nad hotovým `vystup.pdf.vygenerovat_pdf` |
| — | `5c8ef26` | oprava (audit appky): PDF popiska "Řešení: ULOZENO" na nástěnce nahrazena vynecháním věty pro neřešená data; dočasný PDF soubor se uklidí i při výjimce |
| 8 | `dd428dd` | admin: ruční úpravy - klik na nezamčenou buňku cykluje volno→D→N→volno (`POST /rozpis/bunka/{id}/{datum}`); nový `solver/validace.py` (validovat_rozpis) kontroluje tvrdá pravidla na hotovém rozpisu a jen OZNAČÍ porušení (neblokuje uložení - realita > solver); `Schedule.zamcene` nové pole, vyplňuje ho jen `schedule_z_db`. **UI editace buňky přepracováno v Úkolu 9 níž** - zámečky v buňkách i tenhle jednoduchý cyklus jsou pryč. |
| 9 | `3d840d9` | zamykání + přegenerování zbytku + diff - solver bere zamčené směny jako pevný vstup (`Config.pevne_smeny`), takže "vygenerovat" a "přegenerovat zbytek" jsou fakticky stejná operace; `POST /rozpis/generovat` zamkne minulost, spočítá diff proti uloženému stavu, neprázdný diff čeká na potvrzení (`/rozpis/generovat/potvrdit`); nesplnitelnost po zamčení nabídne "Odemknout budoucí zamčené směny". **Ruční úprava buňky přepracována na přání** (viz níž) - žádné zámečky/rozsah v UI, zatržítko "Povolit ruční úpravu" + JS cyklus volno/D/N/DOV/OST/NEM potvrzený Enterem, který rovnou přegeneruje a uloží zbytek měsíce OD upraveného dne (jiní lidé ten den zůstávají volní, aby šlo doplnit náhradu po odebrání někoho ze směny) |
| — | *(nekomitnuto)* | **oprava (na přání po testování Úkolu 9):** ruční úprava buňky (`POST /rozpis/bunka/...`) už NEZAMYKÁ upravenou D/N směnu ani dny před ní natrvalo - jen dočasně přes `Config.pevne_smeny` pro JEDEN doprovodný přepočet (zamkne→vyřeší→odemkne), pak zůstane v DB nezamčená. Trvale se zamyká jen skutečná minulost (`zamknout_minulost`), stejně jako u hlavního tlačítka "Vygenerovat". Důvod: omylem kliknutá buňka se dřív nedala vzít zpět (natrvalo zamčená, žádné UI na odemknutí po odstranění zámečků z mřížky) - přesně to uživatel po testování nahlásil. `<td>` s `not bunka.editovatelna` teď dostává `zamcena` CSS třídu obecně (dřív jen skutečně zamčené), legenda/nápověda vysvětlují, že vícedenní/mimo-cyklus nedostupnost (DOV rozsah, celoměsíční NEM/POZADAVEK) se klikem záměrně nedá upravit - jde jen přes Nedostupnosti. |
| — | *(nekomitnuto)* | **oprava (skutečná příčina "nejde kliknout"):** volná (prázdná) buňka měla klikací `<button>` úplně BEZ obsahu (`bunka.text` je pro volno `""`) - v prohlížeči vypadala, že tam není co kliknout, přidat směnu na volný den tak prakticky nešlo (na rozdíl od D/N/DOV/NEM buněk, které aspoň barvou/textem naznačí obsah). Zjištěno až přímým vykreslením HTML (TestClient), ne jen code review. Oprava: prázdná buňka teď v tlačítku ukáže ztlumenou tečku (`&middot;`, třída `bunka-tlacitko-prazdna`) - DOV/NEM zůstávají beze změny (mají barvu, tečka by kazila zavedený "jen barva" vzhled). Prohození služeb mezi lidmi jde přes dvě takové úpravy (jednomu na volno, druhému na D/N) - napověda pod mřížkou to teď zmiňuje. |
| 9c | *(nekomitnuto)* | nový profil **"optimalizovany"** (na přání, upřesněno: "optimalizovat" = co nejméně krizových dnů, ne jen vyšší váha) - CHECK na `nastaveni.profil` rozšířen o třetí hodnotu (přetvoření tabulky, migrace na `data/rozpis.db` provedena - viz sekce níž), `<select>` na mřížce i formulář `/admin/nastaveni` o profil rozšířené. Priorita "co nejméně krizových dnů" je řešená **dvoufázově** v solveru (`solver/core.py:generate_schedule(..., prioritizovat_obsazeni=True)`), ne vyšší vahou - zkoušelo se nejdřív jen vysoká `vahy.plne_obsazeni` (matematicky dominantní), ale na reálných datech to ZHORŠILO výsledek (10 → 19 krizových dnů, CP-SAT search heuristiky jsou citlivé na rozptyl velikostí koeficientů). Fáze 1 (1/3 času) najde nejvyšší dosažitelný počet plně obsazených D/N slotů bez férovosti v cíli, fáze 2 (2/3 času) ho vynutí jako tvrdé minimum a doladí férovost - s `AddHint` řešením fáze 1 (jinak fáze 2 na složitějším zadání nestíhala najít přípustný bod znovu od nuly - viz `tests/test_solver.py::test_prioritizovat_obsazeni_nikdy_nedopadne_hur_nez_bez_neho`). Na reálných datech: 7 krizových dnů místo 10 u normálního profilu. |
| — | *(nekomitnuto)* | **audit appky:** 3 nálezy - `POST /rozpis/bunka/...`, `/admin/nedostupnosti/nova` a `/admin/zamestnanci/novy` (dvojice_s) nekontrolovaly, že zadané id zaměstnance existuje, než ho poslaly do INSERTu - neplatné id (stará URL po smazání zaměstnance, zmizelý partner mezi zobrazením a odesláním formuláře) spadlo na syrový `sqlite3.IntegrityError` (cizí klíč) → HTTP 500 místo čitelné chyby/404 jako u ostatních rout. |

**Testy:** 352+, celá sada zelená. Spouštět vždy
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

- **Úkol 9b** — samoobslužné podávání požadavků (zapsáno v
  `zadani-faze3-web.md`, revize dřívějšího "NEIMPLEMENTUJE SE") — DALŠÍ
  NA ŘADĚ, nezačato (volitelné, ne blokující - hlavní tok 1-9 je hotový).
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

## ✅ Migrace na `data/rozpis.db` provedena (úkol 9c, profil "optimalizovany")

Stejný vzor jako výš (CHECK vyžaduje přetvoření tabulky). `nastaveni`
byla v reálné DB prázdná (0 řádků), takže šlo jen o `RENAME`+`CREATE`+
`INSERT SELECT`+`DROP`, žádná data se neztratila. Ověřeno:
`PRAGMA integrity_check` = ok, `foreign_key_check` = []. Záloha:
`data/rozpis.db.pred-migraci-optimalizovany-profil.bak`.

## ✅ Kontrola `požadavky.txt` proti DB (na vyžádání, 17.7.2026)

Uživatel chtěl porovnat `nedostupnost` v DB s originálním importním
souborem `požadavky.txt`, ať se najdou záznamy omylem vzniklé
testováním ruční úpravy buňky. Soubor v repu chybí (gitignorovaný,
nejspíš smazaný po importu), uživatel jeho obsah vložil přímo do
konverzace. Ručně ověřeno proti pravidlům `db/import_txt.py`
(rozpoznat_typ/je_konec_pomeru) - **výsledek: shoda, nic navíc ani
chybějícího**. 19 z 21 řádků → 19 záznamů `nedostupnost`, typ/rozsah/
`zakazana_smena` sedí přesně; zbylé 2 řádky ("končí") správně nejsou
nedostupnost, ale `aktivni_do=2026-08-16` u Giňové i Michnové. Obava z
testováním omylem vzniklých požadavků se nepotvrdila.

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
- **Úkol 7 rozhodnutí bez explicitního zadání:** `/rozpis/prepis` a
  `/rozpis/pdf` jsou přístupné OBĚMA rolím (stejně jako `/rozpis`, nahled
  jen aktuální měsíc) - zadání to neřeklo výslovně (na rozdíl od
  úkolů 4-6, které mají v názvu "admin:"). Odůvodnění: přepis neukazuje
  nic, co by nahled neviděl už na mřížce (žádná poznámka), a "PDF na
  nástěnku" dává smysl i pro čtení, ne jen generování. Pokud se ukáže,
  že to má být jen pro admina, stačí přidat `Depends(vyzadovat_admina)`.
- **Úkol 9 - ruční úprava buňky VYŽADUJE JS** (na rozdíl od zbytku appky,
  kde JS jen vylepšuje - "Vanilla JS jen kde nutný" ze zadání, tady je
  fakt nutný): klik cykluje hodnotu jen v prohlížeči, Enter teprve pošle
  zvolenou hodnotu na server. Bez JS zůstane zatržítko "Povolit ruční
  úpravu" bez efektu (tlačítka jsou `type="button" disabled`, ne
  `type="submit"`) - úprava jde bez JS jen přes CLI (repo funkce
  `nastavit_smenu`/`nastavit_nedostupnost_jednoho_dne` existují, CLI
  příkaz zatím ne).
- **Úkol 9 - "odemknout konfliktní směny" zjednodušeno:** zadání chce
  radu při nesplnitelnosti po zamčení. Přesně určit, KTERÁ zamčená
  směna kolizi způsobila, by vyžadovalo zkoušet kombinace (postupně
  odemykat a řešit znovu) - místo toho `/rozpis/generovat/odemknout-a-zkusit`
  natvrdo odemkne VŠECHNY budoucí (datum > dnes) zamčené směny v měsíci a
  zkusí to znovu. Funguje to (otestováno), ale je to pragmatická
  náhrada, ne přesná diagnostika.
- **Úkol 9 design se změnil za chodu** (na přání, po prvním hotovém
  návrhu): původně zámečky v každé buňce + samostatný formulář
  "zamknout/odemknout rozsah dat" (`POST /rozpis/zamek/...`,
  `/rozpis/zamek-rozsah`) - obojí smazáno, nahrazeno zatržítkem
  "Povolit ruční úpravu" + rozšířeným cyklem (D/N/volno/DOV/OST/NEM) a
  automatickým přegenerováním zbytku měsíce po každé ruční úpravě.
  Automatické zamykání minulosti (`zamknout_minulost`) a `Config.pevne_smeny`
  v solveru zůstaly beze změny - jen UI pro ruční (od)mykání zmizelo.

## Zavedené konvence z průběhu (nejsou v zadání explicitně, ale ustálily se)

- Sdílená logika mezi PDF, mřížkou a přepisem (úkol 7) jde přes
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
