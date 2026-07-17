# Fáze 3+ — webové rozhraní (finální zadání pro Claude Code)

Jednotlivé úkoly zadávej po jednom: úkol → testy → commit → /clear.
Úkol 0 proveď PŘED vším ostatním — sladí CLAUDE.md s tímto zadáním,
jinak si budou instrukce protiřečit.

## Hlavní scénář (tomu je podřízeno všechno)

Vedoucí otevře web, přihlásí se, zadá nedostupnosti a požadavky na příští
měsíc, klikne "Vygenerovat" — a dostane rozpis, který ručně přepíše do
Cygnusu. Přepis do Cygnusu je ZÁMĚRNĚ ruční, appka ho nenahrazuje.

Druhý stejně důležitý scénář: velká fluktuace — přidání a odebrání
zaměstnance musí být otázka pár kliknutí, včetně štítků a neslučitelných
dvojic.

Třetí scénář: změna v průběhu měsíce (nemoc) — zamknout co platí,
přegenerovat zbytek, ukázat diff.

## Stack — záměrně minimální

- FastAPI + Jinja2 šablony (server-side rendering, žádné SPA)
- Vanilla JS jen kde nutný — žádný npm, žádný build krok
- Stávající db/, solver/, vystup/ se NEPŘEPISUJÍ — web je tenká vrstva
  nad nimi; db/bridge.py je most DB → solver config
- SQLite, žádný ORM; schéma v db/schema.sql, změny schématu jako
  jednoduché ruční migrační skripty (SQLite CHECK změna = přetvoření tabulky)
- Jeden CSS soubor, barvy jako Cygnus: žlutá = D, modrá = N,
  zelená = DOV, ostatní nedostupnosti bílá/šedá s textem typu
- Konvence repa platí i pro web: kód, komentáře, UI ČESKY
  (uzivatel, smena, vyzadovat_admina — ne users/shift/require_admin)

## Bezpečnostní invarianty (platí pro KAŽDÝ úkol)

1. Reálná jména a osobní data NIKDY do gitu. Trackovaný config.yaml
   obsahuje jen fiktivní ukázková data. Reálná data žijí výhradně
   v gitignorované data/ (SQLite DB). Dokud je repo public, patří do
   .gitignore i DEPLOY.md a .env (detaily serveru, klíče).
2. Každá stránka kromě /login vyžaduje přihlášení. Neexistuje veřejná
   URL s rozpisem. Web se NEDEPLOYUJE, dokud login nefunguje.
3. Hesla bcrypt, server-side session, cookie HttpOnly + Secure +
   SameSite=Lax. Žádný OAuth/JWT.
4. Read-only role nemá routy pro zápis (server vrací 403, nejde jen
   o skryté tlačítko). Read-only vidí mřížku vč. typů nedostupností
   (stejně jako PDF na nástěnce), ale NIKDY poznámky.

## Úkoly

### Úkol 0 — sladit CLAUDE.md a uklidit
- CLAUDE.md, Doménová pravidla: noční obsazení přepsat z "přesně 2" na
  "tvrdě 1–2; normální profil vyžaduje 2, krizový povolí 1" (viz úkol 5)
- CLAUDE.md, Stav: fáze 5 (PDF) označit [x] — vystup/pdf.py je hotový
  vč. testů; nové pořadí fází: login je součást fáze 3 (první úkol),
  deploy zůstává poslední
- rozpis.py (starý prototyp) přesunout do archiv/ ať neslouží jako vzor
- requirements.txt: přidat fastapi, uvicorn, jinja2, bcrypt,
  python-multipart, itsdangerous (nebo ekvivalent pro podepsané session)
- Commit, žádná další funkčnost
- [HOTOVO — commit 48b3b59]

### Úkol 0b — přechod na Python 3.13
Průzkum serveru (DEPLOY.md) zjistil: Debian 13 má jen Python 3.13,
3.12 nelze nainstalovat z apt. ortools 9.15+ má cp313 wheel — ověřeno.
Vývoj musí běžet na stejné verzi jako produkce:
- CLAUDE.md: "Na deploy cílit Python 3.12" → "Python 3.13 (verze na
  produkčním serveru, Debian 13)"
- Lokální .venv přestavět na python3.13, přeinstalovat requirements,
  spustit celou testovací sadu — musí být zelená beze změn kódu
- Pokud by cokoliv na 3.13 nefungovalo, NEŘEŠIT hackem — zastavit se
  a reportovat

### Úkol 1 — kostra webu + přihlášení
- web/app.py (FastAPI), web/sablony/, web/static/
- Nová tabulka uzivatel (jmeno, heslo_hash bcrypt, role: admin|nahled)
  v db/schema.sql + repository funkce ve stylu stávajících
- Login/logout, session, dependency vyzadovat_prihlaseni /
  vyzadovat_admina
- CLI příkaz (rozšířit db/cli.py): vytvořit uživatele, změnit heslo —
  žádná registrace přes web (celkem ~3 účty: 2 admin, 1 sdílený náhled)
- Testy: bez loginu → redirect na /login; role nahled na admin routu → 403

### Úkol 2 — repository pro směny (prerekvizita mřížky)
- db/repository.py dnes směny NEUMÍ (tabulka smena existuje, API ne —
  viz komentář ve schema.sql). Doplnit ve stylu existujících funkcí:
  ulozit_rozpis (smaže nezamčené směny měsíce a zapíše nové),
  smeny_v_mesici, zamknout_smeny(seznam_id) / odemknout,
  smazat_nezamcene_v_obdobi
- Testy: ulozit_rozpis nikdy nepřepíše locked směnu

### Úkol 3 — mřížka měsíce (výchozí stránka pro obě role)
- GET /rozpis?mesic=YYYY-MM, default aktuální měsíc; role nahled vidí
  JEN aktuální měsíc (bez navigace jinam), admin listuje libovolně
- Řádky = zaměstnanci aktivní v daném měsíci, sloupce = dny; víkendy
  vizuálně odlišené; barvy a rozložení co nejblíž PDF/Cygnusu, ať
  vedoucí vidí totéž na zdi i na webu
- Nedostupnosti: barva/typ ano, poznámka jen pro admina (tooltip)
- Pod mřížkou souhrn per zaměstnanec: počet D, N, víkendových směn
  (data už umí _souhrn_tabulka v PDF — stejná logika, ne kopie kódu:
  vytáhnout do sdílené funkce ve vystup/ nebo solver/schedule.py)
- Testy: nahled nevidí poznámku ani jiný měsíc

### Úkol 4 — admin: správa zaměstnanců (fluktuace = priorita)
- Seznam (default jen aktivní, přepínač "i bývalí"), přidání, oprava
  jména, deaktivace k datu — repository funkce už existují
  (pridat_zamestnance, deaktivovat_zamestnance, opravit_jmeno_zamestnance)
- Ve formuláři zaměstnance rovnou: štítky (fyzicka_vypomoc) a
  neslučitelné dvojice (pridat_dvojici existuje) — při nástupu nového
  člověka se vše nastaví na jednom místě
- Tvrdé smazání jen pro záznam bez jediné směny (omyl při zakládání);
  jinak výhradně deaktivace — historie rozpisů se nesmí rozbít
- Nástup/odchod uprostřed měsíce musí solver respektovat (bridge už
  řeší přes aktivni_od/do — ověřit testem)
- Testy: deaktivace zachová historii; nový zaměstnanec od 15. nedostane
  směnu 10.

### Úkol 5 — admin: nedostupnosti + parametry pravidel
- CRUD nedostupností: zaměstnanec, od–do, typ, poznámka
  (pridat_nedostupnost / zrusit_nedostupnost existují; doplnit editaci)
- MIGRACE: CHECK na nedostupnost.typ rozšířit o 'SVZ'
  (DOV/NEM/OST/SVZ/POZADAVEK) — v SQLite = nová tabulka + přelití dat
- Překryvy nedostupností: varování, ne blokace
- Nová tabulka nastaveni + formulář: obsazení D min/max, N min/max,
  max_v_rade, max_smen_mesic, váhy — a DVA pojmenované profily:
  "normalni" (N min 2) a "krizovy" (N min 1, případně vyšší fond)
- config.yaml zůstává jen pro CLI/testy s fiktivními daty
- Testy: změna parametru se propíše do generování; SVZ projde

### Úkol 6 — admin: VYGENEROVAT (jádro hlavního scénáře)
- Velké tlačítko na mřížce: měsíc + profil (normalni/krizovy) →
  solver (přes db/bridge.config_pro_mesic + nastaveni z DB) →
  ulozit_rozpis → mřížka s výsledkem
- Synchronně s time_limit_s (30 s) + indikace běhu; žádné fronty
- Solver z webu VŽDY s num_search_workers=1: server má 2 vCPU sdílené
  s rbscannerem, úloha je malá (rychlost neovlivní) a výsledek je
  deterministický stejně jako v testech
- Při nesplnitelnosti: čitelně zobrazit výstup _diagnostikuj_nesplnitelnost
  + jedním klikem "Zkusit krizový profil"
- Testy: e2e na fiktivních datech; nesplnitelný scénář vrátí diagnostiku,
  ne HTTP 500

### Úkol 7 — pohled pro přepis do Cygnusu
- Přepis je záměrně ruční → dát mu vlastní zobrazení: seznam po
  zaměstnancích (abecedně, jako v Cygnusu), u každého chronologicky
  dny + typ směny/nedostupnosti, velké písmo, řádek po řádku
  odškrtávatelný (jen vizuálně, JS, nic se neukládá)
- Tlačítko "PDF na nástěnku" → existující vystup.pdf.vygenerovat_pdf
  (jen route + download, PDF je hotové)
- Testy: obsah přepisového pohledu odpovídá mřížce

### Úkol 8 — admin: ruční úpravy s validací
- Klik na buňku → cyklus D/N/volno (jen admin, jen nezamčené)
- Po změně validace tvrdých pravidel; porušení zobrazit, ale admin smí
  vědomě uložit (realita > solver), porušené buňky označené
- Testy: validátor chytí N→D, obsazení pod minimem, fond přes limit

### Úkol 9 — zamykání + přegenerování zbytku + diff
- Dny <= dnes zamčené automaticky; budoucí zamykání klikem/rozsahem
- "Přegenerovat zbytek měsíce": locked směny jako fixní vstup solveru
- Diff před uložením: kdo / den / bylo → bude; potvrdit / zahodit
- Při nesplnitelnosti po zamčení: diagnostika + nabídka "odemknout
  konfliktní směny" nebo krizový profil
- Testy: locked se nezmění; diff odpovídá; nesplnitelno po zamčení
  vrací použitelnou radu

### Úkol 9b — samoobslužné podávání požadavků (revize řádku 201–202)
Revize původního rozhodnutí "NEIMPLEMENTUJE SE" níž (Co záměrně NEDĚLAT) —
domluveno 2026 (viz konverzace), typ POZADAVEK v datech už existuje od
začátku, tenhle úkol mu dává vlastní UI a schvalovací workflow místo
ručního zadávání admin/CLI.

- MIGRACE: `nedostupnost` dostane sloupec
  `stav TEXT NOT NULL DEFAULT 'schvaleno' CHECK (stav IN ('podano',
  'schvaleno', 'zamitnuto'))` přes `ALTER TABLE ADD COLUMN` (stejný vzor
  jako `zakaz_smeny`/`max_za_sebou`, SQLite 3.25+ zvládne CHECK bez
  přetvoření tabulky). Výchozí `'schvaleno'` zachová beze změny chování
  všechno, co dnes admin/CLI/import zapisuje přímo.
- `db/bridge.py:config_pro_mesic` bere do solveru jen `stav='schvaleno'`
  — `'podano'` se do rozpisu nepromítne, dokud ho admin neschválí; žádné
  riziko, že se nepotvrzený požadavek stane závazným.
- `'zamitnuto'` se nemaže, zůstává v historii (konzistentní s tím, že se
  v repu nic nemaže).
- Repository (`db/repository.py`, styl stávajících funkcí):
  `pridat_pozadavek(conn, zamestnanec_id, od, do, popis, zakazana_smena=None)`
  — wrapper nad `pridat_nedostupnost` s `typ='POZADAVEK', stav='podano'`;
  odmítne (ValueError), pokud zaměstnanec není aktivní k datu `od`
  (`aktivni_zamestnanci_v_obdobi`). `schvalit_pozadavek(conn, id)` /
  `zamitnout_pozadavek(conn, id)` — UPDATE stav.
- Nová stránka `/pozadavky` (obě role): tabulka kdo / od–do / popis /
  stav + tlačítko "Nový požadavek" (výběr zaměstnance z aktivních,
  kalendář od–do, popis). `POST /pozadavky` smí obě role. Admin navíc
  vidí tlačítka schválit/zamítnout (`POST /pozadavky/{id}/schvalit` a
  `/zamitnout`, 403 pro nahled).
- Systém nepotřebuje vědět, KDO požadavek zadal (sdílený nahled/host
  účet nemá per-osobu identitu) — jen PRO KOHO je určen (výběr
  zaměstnance ve formuláři). Žádné pole "podal" se nepřidává.
- ZMĚNA bezpečnostního invariantu č. 4 (jen pro typ POZADAVEK): nahled
  vidí popis požadavku u VŠECH položek na `/pozadavky`, ne jen svých —
  jinak nemá jak zjistit, jestli se něco vyřídilo. Poznámka u DOV/NEM
  (admin-only, ostatní typy nedostupnosti) zůstává skrytá jako dosud —
  tahle výjimka platí striktně jen pro `/pozadavky` a typ POZADAVEK.
- Testy: pridat_pozadavek odmítne neaktivního zaměstnance; nový
  self-service požadavek má stav 'podano'; config_pro_mesic ignoruje
  'podano'/'zamitnuto', počítá jen 'schvaleno'; nahled smí POST
  /pozadavky, ale dostane 403 na schvalit/zamitnout; existující řádky
  bez sloupce stav (migrace) se chovají jako 'schvaleno' (staré testy
  beze změny).

### Úkol 10 — deploy na Hetzner (až funguje 1–9 lokálně)
Řídí se souborem DEPLOY.md (průzkum serveru 17.7.2026 — Caddy 2.6.2,
rbscanner na 127.0.0.1:8080, Python 3.13, port 8081 volný).
Konkréta pro tento server:
- Vyhrazený systémový účet: useradd --system rozpis; appka v
  /home/rozpis (nebo /opt/rozpis), chown rozpis:rozpis, unit s
  User=rozpis. ZÁMĚRNÁ odchylka od vzoru rbscanneru (User=jaromir):
  data/rozpis.db obsahuje osobní údaje zaměstnanců a izolace účtů
  odděluje obě nesouvisející appky
- rozpis.service dle návrhu v DEPLOY.md: uvicorn web.app:app
  --host 127.0.0.1 --port 8081 (loopback POVINNĚ explicitně),
  EnvironmentFile=.env (chmod 600, vlastník rozpis) s
  ROZPIS_TAJNY_KLIC a ROZPIS_DB
- Caddyfile: přidat blok rozpis-jstl.duckdns.org →
  reverse_proxy 127.0.0.1:8081, BEZ basicauth (appka má vlastní
  login); sudo systemctl reload caddy (reload, ne restart)
- DuckDNS: subdoménu rozpis-jstl zaregistrovat + vytvořit systemd
  timer (vzor rag-sync.timer na serveru) s denním curl update pro OBĚ
  subdomény — nahrazuje dnešní nezdokumentovaný/neexistující
  mechanismus (DEPLOY.md bod 6)
- Swap: vytvořit 2G swapfile (fallocate, mkswap, swapon, fstab) —
  server má 3.7 GiB RAM bez swapu (DEPLOY.md riziko 3)
- Záloha: cron/timer pod účtem rozpis se
  sqlite3 data/rozpis.db ".backup /home/rozpis/zalohy/rozpis-$(date).db",
  rotace posledních ~14 kopií (NE prosté cp za běhu)
- Po nasazení ověřit zvenčí: bez loginu se nikam nedostaneš; cookie
  má Secure a funguje (běží se za HTTPS)
- RUČNÍ krok pro Jaromíra (ne Claude Code): v Hetzner konzoli ověřit
  Cloud Firewall — příchozí povoleno jen 22/80/443 (DEPLOY.md
  riziko 2); a při první session se sudo ověřit root crontab
  (sudo crontab -l) a výsledek dopsat do DEPLOY.md

## Co záměrně NEDĚLAT
- Žádný React/Vue/HTMX, Tailwind, Docker, async fronty, websockety
- Žádný export/API směrem do Cygnusu — přepis je záměrně ruční
- Žádná samoobslužná registrace či reset hesla e-mailem
- ~~Zadávání požadavků zaměstnanci se NEIMPLEMENTUJE~~ — revidováno,
  viz Úkol 9b (typ POZADAVEK v datech existoval od začátku právě pro
  tenhle případ)
