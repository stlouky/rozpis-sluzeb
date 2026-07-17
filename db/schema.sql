-- Schéma databáze pro rozpis služeb (fáze 2).
--
-- Zaměstnanci se NIKDY nemažou - kvůli fluktuaci musí historie rozpisů
-- zůstat konzistentní. Odchod se řeší nastavením aktivni_do (NULL = stále
-- aktivní), viz CLAUDE.md.

CREATE TABLE IF NOT EXISTS zamestnanec (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jmeno TEXT NOT NULL,
    aktivni_od TEXT NOT NULL,   -- ISO datum YYYY-MM-DD
    aktivni_do TEXT,            -- ISO datum, NULL = stále aktivní
    stitky TEXT NOT NULL DEFAULT '',  -- čárkou oddělené, např. "fyzicka_vypomoc"
    -- NULL = platí společný strop z config.yaml (pravidla.max_smen_mesic).
    -- Jinak individuální strop jen pro tohohle člověka (např. brigádník/-ce
    -- se sníženou kapacitou) - viz solver.Config.max_smen_mesic_override.
    max_smen_mesic INTEGER,
    -- Trvalé osobní omezení typu směny (na rozdíl od nedostupnost.zakazana_smena,
    -- které je časově ohraničené na konkrétní interval) - NULL = žádné,
    -- 'D'/'N' = tenhle typ směny nesmí mít NIKDY, v žádném měsíci (zdravotní
    -- apod. důvod) - viz solver.Config.zakazane_smeny, promítá se tam pro
    -- všechny dny měsíce.
    zakaz_smeny TEXT CHECK (zakaz_smeny IN ('D', 'N')),
    -- Osobní strop směn v řadě (typicky zdravotní důvod) - NULL = platí
    -- společné pravidla.max_v_rade - viz solver.Config.max_v_rade_override.
    max_za_sebou INTEGER
);

-- Nedostupnost je INTERVAL (od-do), ne jednotlivé dny - dovolená se zadává
-- jako jeden záznam "3.-9.", ne 7 samostatných dnů.
CREATE TABLE IF NOT EXISTS nedostupnost (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zamestnanec_id INTEGER NOT NULL REFERENCES zamestnanec(id),
    od TEXT NOT NULL,           -- ISO datum, včetně
    do TEXT NOT NULL,           -- ISO datum, včetně
    -- SVZ = školení v zařízení (úkol 5). CHECK na existující sloupec
    -- vyžaduje v SQLite přetvoření tabulky, ne prosté ALTER TABLE ADD
    -- COLUMN (na rozdíl od zamestnanec.zakaz_smeny/max_za_sebou výš) -
    -- migrace na existující data/rozpis.db je popsaná v STAV-FAZE3.md.
    typ TEXT NOT NULL CHECK (typ IN ('DOV', 'NEM', 'OST', 'SVZ', 'POZADAVEK')),
    poznamka TEXT,
    -- NULL = celý den nedostupný. 'D'/'N' = jen tenhle typ směny je
    -- zakázaný, zbylý typ zůstává k dispozici (viz solver.zakazane_smeny).
    zakazana_smena TEXT CHECK (zakazana_smena IN ('D', 'N'))
);

-- Zatím jen tabulka bez repository API - plnit se bude ve fázi 3-4
-- (generování/zamykání/přegenerování).
CREATE TABLE IF NOT EXISTS smena (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zamestnanec_id INTEGER NOT NULL REFERENCES zamestnanec(id),
    datum TEXT NOT NULL,
    typ TEXT NOT NULL CHECK (typ IN ('D', 'N')),
    locked INTEGER NOT NULL DEFAULT 0,
    stav TEXT,
    UNIQUE (zamestnanec_id, datum)
);

CREATE TABLE IF NOT EXISTS dvojice (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zamestnanec_a_id INTEGER NOT NULL REFERENCES zamestnanec(id),
    zamestnanec_b_id INTEGER NOT NULL REFERENCES zamestnanec(id),
    -- 'rozprostrit' = měkké (penalizace, spolu smí když jinak nejde),
    -- 'zakazano' = tvrdé (spolu nesmí NIKDY, viz solver.Config.zakazane_dvojice)
    typ TEXT NOT NULL DEFAULT 'rozprostrit' CHECK (typ IN ('rozprostrit', 'zakazano'))
);

-- Uživatelské účty pro webové rozhraní (fáze 3). Bez registrace přes web -
-- zakládají se výhradně přes CLI (db/cli.py vytvorit-uzivatele), viz
-- zadani-faze3-web.md, bezpečnostní invarianty.
CREATE TABLE IF NOT EXISTS uzivatel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jmeno TEXT NOT NULL UNIQUE,
    heslo_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'nahled'))
);

-- Parametry pravidel pro generování (úkol 5, rozšířeno úkol 9c) - tři
-- pojmenované profily: "normalni" (běžný provoz, noční min 2), "krizovy"
-- (dočasně snížené noční minimum na 1, viz CLAUDE.md) a "optimalizovany"
-- (stejná tvrdá pravidla jako normalni, ale váhy posunuté ve prospěch
-- plného obsazení 4D/2N na úkor férovosti - viz web/app.py:VYCHOZI_VAHY).
-- Řádek pro daný profil vzniká, až ho admin poprvé uloží přes formulář -
-- do té doby config_pro_mesic bere hodnoty z config.yaml beze změny (viz
-- db/bridge.py) - config.yaml tak zůstává jen pro CLI/testy s fiktivními
-- daty, produkční data žijí tady.
CREATE TABLE IF NOT EXISTS nastaveni (
    profil TEXT PRIMARY KEY CHECK (profil IN ('normalni', 'krizovy', 'optimalizovany')),
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
