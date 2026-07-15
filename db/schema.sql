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
    stitky TEXT NOT NULL DEFAULT ''  -- čárkou oddělené, např. "fyzicka_vypomoc"
);

-- Nedostupnost je INTERVAL (od-do), ne jednotlivé dny - dovolená se zadává
-- jako jeden záznam "3.-9.", ne 7 samostatných dnů.
CREATE TABLE IF NOT EXISTS nedostupnost (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zamestnanec_id INTEGER NOT NULL REFERENCES zamestnanec(id),
    od TEXT NOT NULL,           -- ISO datum, včetně
    do TEXT NOT NULL,           -- ISO datum, včetně
    typ TEXT NOT NULL CHECK (typ IN ('DOV', 'NEM', 'OST', 'POZADAVEK')),
    poznamka TEXT
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
    typ TEXT NOT NULL DEFAULT 'rozprostrit' CHECK (typ IN ('rozprostrit'))
);
