# Personal Shopper — brugt børnetøj (Reshopper + DBA + Sellpy)

Overvaager Reshopper.com, DBA.dk OG Sellpy.dk for annoncer der matcher en
ønskeseddel, beregner **bundling pr. sælger PR. KILDE** (fragt-økonomi — se
`bundling.py`; en Reshopper- og en DBA-sælger grupperes ALDRIG sammen,
selv med samme navn) og skriver resultatet til et Google Sheet-dashboard
(og til den hostede webapp, se "Ønskeseddel" nedenfor). MVP for branch
"Brugt børnetøj", byggeagenten Esben satte i gang 2026-07-09. DBA blev
tilføjet som ny kilde (G1) samme dag, Sellpy (G8) 2026-07-10 -- Sellpy er
konsignation (fælles "sælger") og danner derfor ALDRIG en bundle, se
`bundling.py`'s `NON_BUNDLEABLE_SOURCES`.

Se `../personal-shopper-brief.md` for den fulde opgavebeskrivelse,
`BACKLOG.md` for prioritering + F1-spikens fund om Reshoppers tekniske
virkelighed (styrer scraping-tilgangen nedenfor) og G1-fund/G1-levering
om DBA (login-session, shadow-DOM-fund, hydration-JSON).

Read-only — ingen køb, beskeder til sælgere eller kontooprettelse (se briefens §8).

## Opsætning

```bash
cd personal-shopper
python3.11 -m venv .venv        # Playwright kraever Python >=3.10 -- systemets python3 (3.9) er for gammel
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium     # kun noedvendigt foerste gang -- genbruger ~/Library/Caches/ms-playwright
                                 # hvis en anden Playwright-installation paa maskinen allerede har chromium
```

### Google Sheets-opsætning (ÉT manuelt engangstrin)

Scriptet forsøger automatisk at oprette et nyt Google Sheet
(`client.create()`, som opgavebeskrivelsen bad om) og dele det med
`esbvall@gmail.com`. **Dette fejler i praksis** — bekræftet ved direkte test
2026-07-08/09: det genbrugte service account
(`ejendom-server@ejendomsystem-493221.iam.gserviceaccount.com`) har **0
Drive-lagerkvote**. Både Drive-API'ets `files.create` og Sheets-API'ets
`spreadsheets.create` svarer 403 ("Service Accounts do not have storage
quota" / "PERMISSION_DENIED"). Dette er en kendt, dokumenteret
Google-begrænsning for service accounts uden et Shared Drive (som kræver
Google Workspace, ikke en almindelig Gmail-konto) — **ikke en bug i koden**.
Det eksisterende `ejendompython`-ark løser præcis det samme problem ved at
lade et rigtigt Google-menneske eje arket og blot dele det med
service accountet — samme løsning bruges her:

1. Opret et tomt Google Sheet i din egen Google-konto (`esbvall@gmail.com`).
2. Del det med `ejendom-server@ejendomsystem-493221.iam.gserviceaccount.com`
   som **redigeringsberettiget** (Editor).
3. Kopiér spreadsheet-ID'et fra URL'en
   (`https://docs.google.com/spreadsheets/d/<ID_HER>/edit`).
4. Sæt det ind i `config.yaml`:
   ```yaml
   google_sheets:
     spreadsheet_id: "<ID_HER>"
   ```
5. Kør `python monitor.py` som normalt — nu skrives der direkte til dit ark.

Selve skrive-mekanikken (oprette faner, skrive/formatere celler) ER
bekræftet at virke i praksis — testet direkte mod det allerede-delte
`ejendomsystem_sheets`-ark under udviklingen af dette projekt.

Hvis intet spreadsheet er konfigureret ENDNU, falder scriptet automatisk
tilbage til at skrive `matches_fallback.csv` og `bundles_fallback.csv`
lokalt, så resultaterne ikke bare forsvinder mens det manuelle trin
mangler (se `sheets_output.write_local_csv_fallback`).

### DBA-opsætning (login-session, FORUDSÆTNING for kilden)

DBA laaser sælgernavn/-profil bag login for anonyme klienter. Kilden
(`sources/dba.py`) laeser DERFOR en Playwright `storage_state`-fil med en
allerede logget-ind session — **`.dba_storage_state.json`** i
projektroden (samme mappe som denne README, IKKE i git, se
`.gitignore`). Uden den fil springer `sources/dba.py` DBA-kilden helt
over (logget tydeligt, crasher ikke resten af scriptet).

**Filen findes IKKE endnu / er udløbet — sådan genskabes den:**

1. Log ind MANUELT (almindelig browser, ingen automatisering) på
   `https://www.dba.dk` med den dedikerede DBA-konto
   (`firstdawndigital@gmail.com`). DBA/Vend-loginet har en Google
   reCAPTCHA på selve login-siden — den skal løses af et menneske, IKKE
   forsøges omgået af et script (bevidst ikke bygget, se BACKLOG.md's
   G1-fund).
2. Installér browser-udvidelsen **"Cookie-Editor"** (Chrome/Firefox) og
   eksportér cookies for `dba.dk` som JSON, mens du er logget ind.
3. Konvertér den eksporterede cookie-JSON til Playwright
   `storage_state`-format (`{"cookies": [...], "origins": [...]}`) og gem
   som `.dba_storage_state.json` i projektroden.
4. Kør `python monitor.py --dry-run --source dba` og tjek loggen — en
   linje der advarer om "login-session ser UDLOEBET/UGYLDIG ud" betyder
   at trin 1–3 skal gentages. Ingen fejl betyder sessionen virker.

**VIGTIGT:** ingen automatisering i dette projekt forsøger nogensinde at
logge ind, løse CAPTCHA'en eller forny denne fil selv — det er en bevidst
grænse (se BACKLOG.md's G1-fund), ikke en manglende feature. Sessionen
udløber efter ukendt tid (typisk uger til måneder) og skal genskabes
manuelt af Esben ved behov — se `config.yaml`'s `dba.storage_state_file`
for stien der bruges.

## Ønskeseddel

**VIGTIGT (G8, 2026-07-10):** `wishlist.source` i `config.yaml` er nu
`"turso"` i produktion — ønskesedlen redigeres i **webappen**
(https://firstdawndigital.github.io/Plagg/), IKKE i Google Sheetets
"Ønskeseddel"-fane. Den fane laeses ALDRIG mere af `monitor.py` saa laenge
`source: "turso"` staar i config.yaml (se J4 i BACKLOG.md's kritikrunde
2026-07-10) — der staar en advarsel skrevet direkte ind i selve fanen i det
live Sheet om dette. Redigér KUN Sheet-fanen hvis `wishlist.source` bevidst
saettes tilbage til `"sheet"`.

Tre kilder, valgt via `wishlist.source` i `config.yaml`:

- **`"turso"`** (AKTIV i produktion) — den hostede Turso-database bag
  webappen. CRUD sker via webappens `/api/wishlist`-endpoints
  (`turso_io.py`), ikke via denne kodebase direkte.
- **`"local"`** — `data/wishlist.local.yaml`. Indeholder de to officielle
  valideringsposter fra briefen: Birkholm leggings str. 104, Zara bukser
  str. 104. Bruges til at unit-teste matching/bundling uden Sheets/Turso-
  adgang, og som fallback hvis den valgte kilde ikke kan naas.
- **`"sheet"`** (IKKE laengere aktiv i produktion) — en fane (standard:
  `Ønskeseddel`) i samme Google Sheet som dashboardet, med kolonnerne
  Type / Mærke / Størrelse / Maks-pris / Stand (rækkefølge ligegyldig,
  kolonnenavne matches case-insensitivt, se `wishlist.py:COLUMN_ALIASES`).

## Kør

```bash
python monitor.py               # rigtig koersel: begge kilder, skriver til Sheets/DB
python monitor.py --dry-run     # koer uden at skrive noget som helst
python monitor.py --source dba  # koer kun én kilde (reshopper eller dba)
```

## Trigger-fra-Sheet ("Kør nu"-knap, I1)

Systemet koerer normalt kun 2x dagligt (se launchd-eksemplet nedenfor). Hvis
Esbens kone vil se opdateret data NU (fx efter at have tilfoejet nye ting til
ønskesedlen), kan hun selv trigge en koersel direkte fra Sheetet -- ingen
terminal noedvendig.

**Sådan bruges det (i Sheetet):**

1. Aabn fanen **"Kontrolpanel"** (oprettes automatisk foerste gang
   `trigger_watcher.py` koeres, se nedenfor).
2. Saet hak i **"Kør nu"**-checkboxen (celle B2 -- en rigtig Sheets-checkbox,
   ikke tekst).
3. **"Status"**-cellen skifter til "Kører..." indenfor `poll_interval_s`
   sekunder (standard 60), og til "Færdig kl. HH:MM (N matches, M bundles)"
   naar koerslen er faerdig (typisk et par minutter, se Playwright-delays).
   Ved fejl vises "Fejlede: <kort besked>" i stedet.
4. Checkboxen nulstilles automatisk til tomt/falsk naar koerslen er faerdig
   (uanset succes/fejl), saa den samme koersel ikke trigges igen og igen.
5. **"Sidst kørt"**-cellen faar koerslens tidsstempel.

**Forudsætning:** `trigger_watcher.py` skal koere som en LOENGEREVARENDE
proces ved siden af -- den er IKKE noget der starter/stopper af sig selv.
Start den manuelt til test:

```bash
python trigger_watcher.py                    # poller kontinuerligt (Ctrl+C stopper paent)
python trigger_watcher.py --once             # tjekker checkboxen ÉN gang og afslutter (test)
python trigger_watcher.py --poll-interval-s 5  # kortere interval (test)
```

Poll-loopet laeser KUN "Kør nu"-cellen hvert `trigger.poll_interval_s`
sekund (ét billigt gspread-kald, ikke hele Sheetet) -- se
`sheets_output.read_run_now()`. Selve koerslen sker som en adskilt
`monitor.py`-subprocess (renere haandtering af Playwrights asyncio-event-loop
og logging-handlers end at importere og kalde `monitor.main()` gentagne
gange i samme proces).

For at holde `trigger_watcher.py` koerende permanent i baggrunden (fx efter
en genstart af Macen), brug launchd med `KeepAlive` (IKKE
`StartCalendarInterval`, som er til periodiske engangs-koersler --
`trigger_watcher.py` skal blive ved med at koere kontinuerligt).
**IKKE installeret automatisk**, samme praksis som det 2x-dagligt
scheduled-task nedenfor:

Opret `~/Library/LaunchAgents/com.local.personal-shopper-trigger.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.personal-shopper-trigger</string>
  <key>ProgramArguments</key>
  <array>
    <string>/absolut/sti/til/personal-shopper/.venv/bin/python3</string>
    <string>/absolut/sti/til/personal-shopper/trigger_watcher.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/absolut/sti/til/personal-shopper</string>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/absolut/sti/til/personal-shopper/trigger_watcher_stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/absolut/sti/til/personal-shopper/trigger_watcher_stderr.log</string>
</dict>
</plist>
```

Aktivér:

```bash
launchctl load ~/Library/LaunchAgents/com.local.personal-shopper-trigger.plist
```

Deaktivér:

```bash
launchctl unload ~/Library/LaunchAgents/com.local.personal-shopper-trigger.plist
```

`KeepAlive` genstarter processen automatisk hvis den skulle crashe (den boer
i praksis aldrig goere det -- se `trigger_watcher.py`'s brede try/except
omkring selve koerslen), i modsaetning til `StartCalendarInterval` som kun
starter processen paa faste tidspunkter og lader den afslutte igen (bruges
til `monitor.py`'s 2x-dagligt-koersel nedenfor, IKKE til denne watcher).

**Begraensning:** koer IKKE en manuel `python monitor.py` samtidig med at
`trigger_watcher.py` har trigget en koersel (og omvendt) -- begge skriver
til samme `seen.db` og samme Sheet-faner. Det 2x-dagligt scheduled-task
(næste afsnit) og `trigger_watcher.py` kan sagtens koere som to separate,
permanente processer ved siden af hinanden -- de overlapper i praksis
sjaeldent (koerslerne tager et par minutter, launchd-tidspunkterne er faste),
men hvis det skulle ske, er det seneste skriv der vinder (ingen laasning
paa tvaers af de to processer pt.).

## Hvad der sker under motorhjelmen

1. **`wishlist.py`** indlæser ønskesedlen (Sheet-fane eller lokal fil).
2. **`monitor.py`** bygger søgetermer ("`<mærke> <type>`") ud fra
   ønskesedlens rækker og kører DENNE fase for HVER kilde i
   `SOURCE_MODULES` (pt. `reshopper` og `dba`) via den fælles
   `run_source()`-funktion.
3. **`sources/reshopper.py`/`sources/dba.py`** navigerer direkte til hver
   platforms søge-URL (bekræftet 2026-07-09: begge FILTRERER rent faktisk
   resultaterne — se modulernes docstrings) og parser op til
   `max_results_per_term` annoncekort pr. term.
4. **Fase 1 (billig foerfiltrering)** — `matching.py:precheck()` filtrerer på
   pris/type/størrelse UDEN at besøge en eneste annoncedetaljeside.
5. **Fase 2 (detalje-opslag)** — KUN for kandidater der bestod fase 1 besøger
   `fetch_details()` annoncens egen side. Reshopper udtrækker mærke/stand/
   sælger/fragt fra en standard `application/ld+json` schema.org-Product-blok
   (robust SEO-markup, ikke Tailwind-CSS-selectors). DBA bruger PRIMÆRT en
   intern, server-renderet `window.__staticRouterHydrationData`-JSON-blob
   (sælgernavn, stabil numerisk sælger-ID, fragttekst, præcis dansk
   stand-label) med JSON-LD som fallback — se `sources/dba.py`'s docstring
   for det uventede shadow-DOM-fund der ligger bag dette valg.
6. **`matching.py:match_all()`** ranger de berigede kandidater: "eksakt"
   (type+mærke+størrelse) før "nær match" (nabostørrelse og/eller generisk
   mærke), se briefens §5.
7. **`bundling.py:build_bundles()`** grupperer matches pr. sælger **OG
   kilde** (samme navn på to platforme er IKKE nødvendigvis samme person),
   lægger ÉN fragt til det samlede køb og beregner effektiv pris/stk
   (briefens §6).
8. **`db.py`** dedupliker på tvaers af koersler (SQLite, `seen.db`) og bevarer
   `first_seen` immutabelt selv naar prisen aendrer sig.
9. **`sheets_output.py`** skriver to faner: `Matches` (én raekke pr. match)
   og `Bundles` (én raekke pr. saelger med ≥1 match), begge med en
   "Kilde"-kolonne der viser hvilken platform fundet stammer fra.

## Kildernes robusthed

- **Reshopper** — intet offentligt/uofficielt API fundet (F1-spike,
  BACKLOG.md). Kører via Playwright Chromium, **headless=True** (bekræftet
  at give status 200 på forsiden). `robots.txt` sætter `Disallow: /` for
  generiske bots — Esben har eksplicit godkendt at bygge alligevel, men
  **lavfrekvent og skånsomt**: 5–15s tilfældig delay mellem soegninger/
  detalje-opslag (laengere end PA SPEAKERS-arkivets 3–8s), maks 10 kort pr.
  soegeterm, ingen aggressiv retry. Bot-wall-detektion tjekker BAADE HTTP
  429/`x-vercel-mitigated`-header (primaersignal, Vercel-specifikt) OG danske
  tekstmarkoerer (fallback). Ved bot-wall: logges og springes stille over for
  DENNE koersel — scriptet crasher aldrig som helhed (se
  `sources/reshopper.py`, samme graceful-degradation-princip som
  Kleinanzeigen/Blocket-kilderne i PA SPEAKERS-arkivet).
- **DBA** — `robots.txt` er permissiv (kun `/my-page`, `/messages`,
  `/favorites`, `/profile*`, `/map*` disallowed) — lavere risiko end
  Reshopper, men samme skånsomme 5–15s-kadence alligevel. Kræver en
  logget-ind session (se "DBA-opsætning" ovenfor) — kilden forsøger
  ALDRIG selv at logge ind, løse CAPTCHA eller forny sessionen; ser den
  udløbet ud, stopper kilden og logger en fejl der beder om at eskalere
  til Esben. Sælger/stand/fragt hentes primært fra en intern,
  server-renderet JSON-blob (`window.__staticRouterHydrationData`,
  ikke-officiel struktur), med JSON-LD som fallback — se
  `sources/dba.py`'s docstring for detaljer om DBA's Podium/
  shadow-DOM-arkitektur, som var afgørende for dette designvalg.

## Kendte begrænsninger

- **Kun foerste side af soegeresultater** (~10 kort pr. term) — ingen
  bekræftet infinite-scroll/"vis flere"-trigger fundet ved interaktiv test
  2026-07-09. For smalle maerke+type-kombinationer (som testposterne) er
  dette sjaeldent et problem, men brede generiske soegninger (fx blot
  "leggings" uden maerke) vil kun se en lille brøkdel af de 40.000+ reelle
  traeffere.
- **Ingen sortering efter "nyeste"** — Reshoppers sorterings-dropdown aendrer
  ikke URL'en (client-side state), saa vi bruger standard-relevanssortering.
  Dedup via `seen.db` betyder at allerede-sete annoncer ikke gentages i
  outputtet, men rent NYE annoncer der ligger uden for de foerste ~10 kort
  kan blive overset indtil de rykker laengere op i relevans-sorteringen.
- **Sælger-ID er best-effort** — udtrækkes via regex fra en ikke-officiel,
  indlejret React-Server-Component-JSON-streng (se
  `sources/reshopper.py:_extract_seller_id`). Kan knække ved et
  Reshopper-redeploy uden varsel; falder da tilbage til saelgernavn som
  bundling-groupnoegle (ikke garanteret unikt paa tvaers af platformen).
- **Fragtpris antages ens paa tvaers af én saelgers annoncer** — vi bruger
  den HOEJESTE observerede `shippingRate` blandt en saelgers matchede items
  som bundlens fragtpris (konservativt), da Reshopper ikke oplyser en samlet
  "kurv-fragt" for flere items paa tvaers af annoncer.
- **"Lokal afhentning"-bonus er kun markeret naar schema.org eksplicit
  bekraefter 0-kr. fragt** — manglende fragt-data behandles IKKE som bekraeftet
  gratis afhentning (kunne ogsaa vaere manglende/utilgaengelig data).
- **Ingen aktiv/inaktiv-tracking** — dashboardet viser KUN den seneste
  koersels fund (matchende + prisfiltrerede annoncer), ikke akkumuleret
  historik over solgte/fjernede annoncer. `seen.db` bruges udelukkende til
  `first_seen`-tidsstempler, ikke til at vise gamle fund der ikke laengere
  matcher.
- **Google Sheets auto-oprettelse virker ikke** med dette service account
  (0 Drive-kvote, se "Google Sheets-opsætning" ovenfor) — kræver ét manuelt
  engangstrin.
- **DBA: samme "kun ~10 kort pr. søgeterm"-begrænsning som Reshopper** —
  ingen bekræftet "vis flere"-trigger undersøgt. Betyder at et reelt
  matchende DBA-opslag kan mangle i output hvis det ligger uden for de
  første 10 søgeresultater (bekræftet forekommet under G1-test 2026-07-09).
- **DBA: sælger/stand/fragt afhænger af en udokumenteret intern
  JSON-struktur** (`window.__staticRouterHydrationData`) — kan brække ved
  et DBA/Vend-redeploy uden varsel; falder da tilbage til JSON-LD
  (mærke/stand) eller "ukendt"/tom fragt, aldrig en crash.
- **DBA: login-sessionen udløber uden varsel** — se "DBA-opsætning"
  ovenfor. Ingen automatisk fornyelse; kilden stopper og logger tydeligt
  i stedet for at fejle stille, hvis sessionen ser ugyldig ud.

## Periodisk kørsel med launchd (5× dagligt: 06/10/14/18/22)

**G19 (2026-07-11): INSTALLERET og AKTIV** på denne maskine -- se
BACKLOG.md's G19 for baggrunden (Esbens kone fandt Vinted-annoncer der
ikke dukkede op, delvist fordi der aldrig kørte noget automatisk mellem
manuelle "Kør nu"-tryk). Plist-filen ligger på
`~/Library/LaunchAgents/com.local.personal-shopper.plist` med de
absolutte stier til DENNE maskines `.venv`/repo -- kopiér/tilpas stierne
hvis systemet flyttes til en anden maskine, samme mønster som PA
SPEAKERS-arkivets README.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.personal-shopper</string>
  <key>ProgramArguments</key>
  <array>
    <string>/absolut/sti/til/personal-shopper/.venv/bin/python3</string>
    <string>/absolut/sti/til/personal-shopper/monitor.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/absolut/sti/til/personal-shopper</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>6</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>10</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>14</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>18</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>22</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
  </array>
  <key>StandardOutPath</key>
  <string>/absolut/sti/til/personal-shopper/launchd_stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/absolut/sti/til/personal-shopper/launchd_stderr.log</string>
</dict>
</plist>
```

Aktivér:

```bash
launchctl load ~/Library/LaunchAgents/com.local.personal-shopper.plist
```

Deaktivér:

```bash
launchctl unload ~/Library/LaunchAgents/com.local.personal-shopper.plist
```

Tjek at den er indlæst:

```bash
launchctl list | grep personal-shopper
```

## Udvidelse til flere platforme (senere branch)

Arkitekturen er bevidst lagdelt saa flere kilder kan tilfoejes uden at
røre matching/bundling/output: implementér en ny `sources/<platform>.py`
med samme `fetch(config, dry_run)`-signatur (og evt. `fetch_details()`),
tilføj den til `SOURCE_MODULES` i `monitor.py`. `matching.py`/`bundling.py`
arbejder udelukkende på den normaliserede item-model og er 100% platforms-
agnostiske allerede nu — **bekræftet i praksis ved G1 (DBA)**: `dba.py`
blev tilføjet uden at røre `matching.py` og med kun ét lille (men vigtigt)
rettelse i `bundling.py` (kilde-praefiks i `_seller_key`, se BACKLOG.md).
Sellpy blev bygget (G8, 2026-07-10) via Sellpy.dk's offentlige Algolia-
soegeendpoint (se `sources/sellpy.py`) og indgaar i `SOURCE_MODULES`.
Konsignationsmodellen (fælles fragt/"sælger" for HELE Sellpy-markedet, ikke
pr. individuel sælger) betyder at Sellpy-matches ALDRIG bundlede (J5-fix,
kritikrunde 2026-07-10) — se `bundling.py`'s `NON_BUNDLEABLE_SOURCES`,
Sellpy optræder derfor kun i Matches-listen, aldrig i Bundles. Vinted er
stadig ikke bygget.
