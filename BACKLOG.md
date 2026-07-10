# BACKLOG — Personal Shopper (branch: Brugt børnetøj / Reshopper)

> Fastbredde-tabeller i kodeblokke (ikke markdown-pipe-tabeller) så filen kan
> monitoreres med `cat`/`watch` i en smal tmux-pane uden at ombrydes grimt.
> Hold linjer under ~70 tegn ved redigering. WSJF = CoD / Size, CoD = BV+TC+RR
> (hver 1–10). Fuld kontekst: se [personal-shopper-brief.md](../personal-shopper-brief.md)

**Live demo/dashboard (aktivt i brug):** https://docs.google.com/spreadsheets/d/1EjCrvQmHcTz6MAhSYhQYPCfbB9rTKyscMJJ5ZtNPjO4
(faner "Matches" og "Bundles", opdateret 2026-07-09 — H1-H5 leveret, se nedenfor)

**G5-webapp (live, men IKKE endnu koblet til friske kørsler):** https://firstdawndigital.github.io/Plagg/
(adgangskode "klematis"). Kode pushet til `FirstDawnDigital/Plagg` (repo
gjort offentligt 2026-07-10, da org-planen ikke understøtter Pages fra
private repos -- ingen hemmeligheder i koden, data ligger i Turso, ikke
i repoet). Viser i dag data fra Fase 4-testkørslerne (12 matches, 5
bundles) -- opdateres først med FRISK data når Esben aktivt sætter
`output.targets`/`trigger.source`/`wishlist.source` til `"turso"` i
`config.yaml` (se G5-status).

## Aktiv backlog (næste øverst)

```
ID    Emne                              Prioritet     Status
----  --------------------------------  ------------  --------
G14   Vinted-fix: priming-retry+badges  Size 3        DONE
G15   Størrelse: eksakt/op, aldrig ned  Size 2        NÆSTE
G6    Stand-normalisering (m. punkt 3)  Size 4-5      TODO
G16   Vinted land + polsk-nedprioritet  Size 6-7      TODO (afh. profilside)
G4    Region-filtrering (afhentning)    WSJF 3.5      TODO
G2    Notifikationer (opsummering)      WSJF 4.3      TODO (konens brug)
G3    Beskedudkast + reservation        WSJF 2.0      TODO (konens brug)
```

Leveret (detaljer nedenfor): G5 (webapp LIVE), G7 (størrelse valgfri),
G8 (Sellpy-kilde), G9 (Vinted-kilde), J4-J7 (kritikrunde 2),
G10-G13 (hastighedsoptimering + hængnings-hærdning + status-fix), + bundle-definition
strammet + mobil-layout-fix.

## Refinering (Opus, 2026-07-10) — Esbens 6 nye punkter

**G14 (DONE, 2026-07-10) — Vinted-fix.** Punkt 1 ("Vinted vises ikke") viste sig
IKKE at være en data-bug: Turso indeholdt 28 Vinted-matches (flest af
alle kilder) da det blev undersøgt. Reelle årsager: (a) Vinteds
cookie-priming (`_prime_session()` i `sources/vinted.py`) rammer
intermitterende en DataDome-403 -- 2 af 4 seneste rigtige kørsler fik 0
Vinted-annoncer, og fordi generations-swap OVERSKRIVER alt pr. kørsel,
forsvinder Vinted da HELT fra det publicerede run. Esben har sandsynligvis
kigget lige efter et 403-run. (b) Kosmetisk: `sourceBadgeClass()` i
`docs/index.html` har kun farvede badges for reshopper/dba -- vinted OG
sellpy falder til grå `badge-source`, lette at overse. **Fix (leveret):**
(a) `_prime_session()` prøver nu op til 3× med stigende backoff (2-5s,
4-10s) og roterer mellem 3 browser-UA'er pr. forsøg, før kilden opgives
for kørslen; (b) `badge-vinted` (cyan)/`badge-sellpy` (grøn) CSS+grene
tilføjet i `sourceBadgeClass()`. **Verificeret live:** normal priming
lykkedes på 1. forsøg (anon_id sat); et tvunget 404-scenarie bekræftede
2 forsøg m. korrekt backoff (~5.6s) før pænt None-fald; `fetch()` end-to-
end mod ægte Vinted gav 5/5 hits m. pris/størrelse/mærke/sælger udfyldt;
JS-syntax for `docs/index.html` verificeret med `node --check`. Size 3.

**G15 — Størrelse: eksakt eller næste OP, aldrig mindre.** Punkt 2. I dag
giver `matching._size_rank()` "nær" ved BEGGE nabostørrelser (104 → både
98 og 110). Esben vil: eksakt = bedst, næste størrelse OP (104→110) =
acceptabelt nær-match, MINDRE (104→98) = matcher ALDRIG (barnet vokser).
**Teknisk:** erstat `_neighbor_sizes()`-brugen i `_size_rank()` med kun
`SIZE_LADDER[idx+1]`. Kant-cases: tom ønske-størrelse skal STADIG →
"eksakt" (G7 uændret); Sellpy/Vinted-intervalstørrelser ("98/104")
matcher i dag hverken -- overvej at parse første token. Size 2, ingen
afhængigheder.

**G6 (opdateret — punkt 3 slået sammen hertil) — Stand-normalisering.**
Punkt 3 ER en fuld specifikation af det gamle G6. Hver platform angiver
stand FORSKELLIGT (Reshopper "Næsten som ny"/"God, men brugt"/"Defekt,
kan laves"; Sellpy "Nyt/Meget god/God/Acceptabelt"; Vinted "Ny med
prismærker/.../Tilfredsstillende"; DBA fritekst + CONDITION_MAP-fallback).
**Design:** 5-trins normaliseret skala (ny > næsten_ny > god > brugt >
defekt) med mapping-tabel pr. kilde (nyt `stand_map`-modul eller i
`matching.py`); ønskets `stand`-fritekst mappes til en MINIMUMS-tærskel;
annoncer under tærsklen filtreres/nedtones. Genbrug
`sheets_output.BAD_STAND_LABELS`-mønstret til visning. Ingen skema-
ændring strengt nødvendig (kan beregnes on-the-fly), men en
`stand_norm`-kolonne letter visning. Size 4-5.

**G16 — Vinted land + polsk-nedprioritering (punkt 4+5 slået sammen).**
BEKRÆFTET LIVE: Vinteds anonyme catalog-hit indeholder INTET land
(`user`-objektet har kun business/id/login/photo/profile_url; ingen
city/country nogen steder; `/api/v2/items/<id>` 404'er uden login).
**Esben har besluttet (2026-07-10) at bygge det alligevel** via opslag
af hver sælgers `profile_url`-HTML (1 ekstra kald pr. Vinted-kandidat mod
en DataDome-beskyttet side). Punkt 5 (nedprioritér polske sælgere:
dyr fragt + hyppig parfumelugt) er HÅRDT afhængig af dette og bygges
sammen med det. **Teknisk:** (a) `sources/vinted.py` henter sælgers
profil-HTML og udtrækker land (skånsom kadence, bot-wall-håndtering som
resten); (b) ny DB-kolonne `seller_country` + Turso-skemafelt + visning
(land-flag/tekst pr. Vinted-match i webapp/Sheets); (c) soft
nedrangering i `matching.match_all()`-sort for polske sælgere + synlig
advarsel (parfumelugt/dyr fragt), IKKE hård eksklusion. Size 6-7.
**Reel risiko (ærligt flag fra spike):** usikkert om profilside-opslaget
holder stabilt i drift uden at blive DataDome-blokeret -- byg med tidlig
validering af at det faktisk virker før resten bygges ovenpå.

**Prioriterings-begrundelse:** G14+G15 er små, høj-værdi fixes med nul
afhængigheder (gøres først). G6 (stand) er den tunge, veldefinerede
feature. G16 er størst + mest usikker (bot-risiko) -- placeret efter de
sikre gevinster, men foran G4/G2/G3 fordi Esben aktivt har prioriteret
det. G2/G3 forbliver gated på konens faktiske brugsmønster.

**G10-G12 leveret (2026-07-10) — hastighedsoptimering + hængnings-hærdning:**

Baggrund: en komplet 4-kilde-kørsel tog 14m10s, hvoraf Sheets/Turso-
skrivning kun udgjorde ~3 sekunder (0,3%) -- HELE tiden gik på Reshopper/
DBAs bevidste 5-15s throttling pr. detalje-opslag. At slukke for Sheets
ville altså ikke have givet nogen målbar gevinst.

- **G10 (parallellisering):** de 4 kilder køres nu SAMTIDIGT via
  `ThreadPoolExecutor` i stedet for sekventielt (`monitor.py`) -- hver
  kildes egen kadence/throttling er UÆNDRET, kun at flere kilders
  uafhængige arbejde nu overlapper i tid. SQLite-skrivninger sker
  fortsat udelukkende i hovedtråden (sqlite3 er ikke trådsikkert).
  Målt: **14m10s → 7m25s** (næsten halveret) på en rigtig kørsel, alle 4
  kilder bekræftet startet på samme sekund i loggen.
- **Kilde-fremdriftsindikator:** statusteksten opdateres nu løbende
  efterhånden som hver kilde bliver færdig (fx "Kører... (Sellpy ✓,
  Vinted ✓, DBA …, Reshopper …)"), skrevet til både Sheets Kontrolpanel
  og Turso (afhængig af `output.targets`). Kendt, forventet adfærd (IKKE
  en fejl): et kort vindue hvor alle kilder viser ✓ men status endnu
  ikke er skiftet til det ægte "Færdig" kan forekomme, fordi
  `trigger_watcher.py` først sætter den endelige status EFTER at
  `monitor.py`-processen er helt afsluttet (Sheets/Turso-output +
  process-exit), et par sekunder efter sidste kildes ✓.
- **G11 (detalje-cache):** `db.py`s `listings`-tabel fik en ny
  `details_fetched`-kolonne. En kandidat-annonce der allerede er
  detalje-hentet FØR (uanset om den dengang matchede noget ønske eller
  ej -- vigtigt arkitektur-hul lukket, se nedenfor) springer det dyre
  detalje-opslag helt over ved gensyn; kun prisen opdateres altid fra
  den friske søgeresultat-side. Kun HELT NYE annonce-id'er detalje-
  hentes. `upsert_listing()` har upgrade-only-logik (`details_fetched`
  nedgraderes aldrig 1→0). Bekræftet i praksis: en kørsel viste "55
  kandidater i alt -- 55 allerede komplette fra kortet" for Sellpy, og
  55 rækker fik `details_fetched=1` i databasen selvom kun 10 reelt
  matchede et ønske -- arkitektur-hullet (kun matches blev tidligere
  cachet) er lukket. Reshopper/DBAs fulde tidsbesparelse ved høj
  cache-hit-rate er endnu ikke målt over en komplet kørsel (test blev
  afbrudt undervejs), men mekanismen er verificeret korrekt isoleret.
- **G12 (hængnings-hærdning):** to hængninger er observeret (en 8+
  timers hængning natten 2026-07-09/10 FØR parallellisering, og en
  kortere ~40 min. stilstand under et testforsøg -- sidstnævnte
  formentlig blot en afbrudt forgrundsproces, ikke en kodefejl). Et
  grundigt stress-testbatteri (`test_hang_diagnostics.py`, 36
  iterationer, sekventielt + parallelt, alle 4 kilder) kunne IKKE
  reproducere nogen hængning -- alle kald (inkl. `browser.close()`/
  `context.close()`, som var mistænkte efter parallelliseringen)
  fuldførte sundt (maks 1,85 sek., langt under de eksisterende 25-30s
  timeouts). Rodårsagen til den oprindelige 8-timers-hængning forbliver
  derfor ubekræftet. I stedet er der bygget et generelt sikkerhedsnet
  (`hang_guard.py`): en hård, tråd-baseret proces-watchdog
  (`install_hard_watchdog`, default 22 min.) i `monitor.py`s `main()`
  der GARANTERER at processen aldrig kan hænge stille i timevis igen,
  uanset årsag eller hvordan den kaldes (direkte, via
  `trigger_watcher.py`, eller ad-hoc). **Ærligt forbehold, vigtig
  læring:** et forsøg på at wrappe selve Playwrights `close()`-kald i en
  tråd-baseret timeout blev testet og VISTE SIG at ødelægge Playwrights
  sync-API (`greenlet.error: cannot switch to a different thread`) --
  droppet igen, Playwright-objekter håndteres derfor fortsat direkte/
  synkront, med den globale proces-watchdog som den reelle beskyttelse.
- **G13 (UI-hul fundet 2026-07-10, IKKE en proceshaengning):** Esben
  observerede status fastlåst på "Kører... (DBA …, Reshopper …, Sellpy
  ✓, Vinted ✓)" i over halvanden time. Undersøgt: INGEN `monitor.py`-
  proces kørte -- det var en efterladt status fra en tidligere afbrudt
  testkørsel, ikke en hængning. Rodårsag: kun `trigger_watcher.py`
  skrev tidligere en endelig "Færdig"-status (ved at parse `monitor.py`s
  stdout EFTER at have startet den som subprocess) -- kørte man
  `monitor.py` DIREKTE (test, eller et fremtidigt planlagt job udenom
  trigger_watcher), blev status derfor stående på sidste fremdrifts-
  tekst for evigt, uanset om kørslen reelt lykkedes. Rettet:
  `monitor.py` skriver nu ALTID sin egen endelige status
  (`write_final_status()`) ved afslutning -- succes, alle kilder
  fejlede, eller ingen kilder konfigureret -- uafhængigt af hvordan den
  bliver kaldt. Bekræftet ved en rigtig kørsel: status gik korrekt fra
  "Kører..." til "Færdig kl. 10-07-2026 21:40 (80 matches, 7 bundles)"
  i både Sheets og Turso, skrevet af `monitor.py` selv.

**G9 leveret (2026-07-10):** `sources/vinted.py` -- anonym cookie-priming
(`GET vinted.dk/` sætter `anon_id`/`access_token_web`) + `GET
api/v2/catalog/items?search_text=...`, ingen login. `fetch_details()` er
no-op (fragt bekræftet reelt utilgængeligt anonymt, ikke kun et ekstra
kald væk -- undersøgt via både item-siden ld+json og et 404'et
`/api/v2/items/<id>`-forsøg). Prisfeltet er `price.amount` (EKSKL.
Vinteds obligatoriske købergaranti-gebyr, for fair sammenligning på
tværs af kilder). Børnetøjs-størrelse er format `"<alder> / <cm> cm"` --
cm-tallet parses ud og matcher `matching.SIZE_LADDER` direkte. RIGTIGE
individuelle sælgere (ikke konsignation som Sellpy) -- IKKE i
`NON_BUNDLEABLE_SOURCES`, bundler normalt. Skånsom kadence (5-15s, som
Reshopper/DBA) pga. DataDome/Cloudflare-beskyttelse -- bekræftet i
praksis: en opfølgende test ramte en ægte Cloudflare-challenge (403,
`Cf-Mitigated: challenge`), håndteret gracefully (logget, tom liste,
ingen crash). Testet mod den rigtige 7-item-ønskeseddel: 140 rå hits →
37 kandidater → 21 matches, 0 bundles (ingen sælger optrådte 2 gange i
denne kørsel).

**Kritikrunde 2026-07-10 (Opus, teknisk + UX) — fund der udløste J4-J7:**
- **J4 (kritisk):** `wishlist.source=turso` gør Google Sheetets
  "Ønskeseddel"-fane reelt død (læses aldrig mere), men intet i Sheetet
  eller dokumentationen siger det -- redigerer Esbens kone fanen der
  (gammel vane), sker der intet, lydløst. `README.md`/`wishlist.py`s
  docstrings er også forældede (nævner kun sheet/local, ikke turso).
- **J5 (moderat):** Sellpy er konsignation (alt "sælges" under ét
  fælles navn "Sellpy") -- bundling.py grupperer derfor usammenhængende
  Sellpy-fund (fx leggings+duplo+jakke) til én kunstig "bundle" der
  næsten altid "betaler sig", og udvander signalet. Bekræftet i live
  data (run_id=20: 11 usammenhængende items i én "Sellpy"-bundle).
- **J6 (moderat):** "kan tage flere minutter" undersælger stadig et
  14-minutters-vindue (bekræftet i log efter Sellpy blev tilføjet).
- **J7 (lav):** `sources/sellpy.py`s docstring lover en
  voksentøjs-udelukkelse der ikke holder for størrelsesløse ønsker
  (G7-regression) + generel README/config-kommentar-doc-rot.
- **Positivt bekræftet:** ingen mobil-overflow, størrelses-udelukkelse
  virker korrekt for ønsker MED størrelse.
- **Erkendt spænding, IKKE en bug:** ønskeseddel øverst (Esben-ønske)
  betyder en travl bruger scroller forbi 7 ønsker + formular før
  bundles/matches. Løses ved at flytte TL;DR-banneret til at stå FØR
  ønskesedlen (handl-nu-signalet synligt med det samme), uden at rykke
  selve ønskeseddel-sektionen væk fra toppen igen.

**J4-J7 leveret (2026-07-10, udviklingsrunde i Sonnet):**
- **J4:** `wishlist.py`/`README.md`s docstrings opdateret til at nævne
  alle tre kilder (sheet/local/turso) med turso som aktiv. En rød,
  iøjnefaldende advarsel er skrevet DIREKTE ind i det live Google
  Sheets "Ønskeseddel"-fane (række 1via gspread): "⚠️ Denne fane bruges
  ikke længere til at finde ønsker -- rediger i webappen:
  https://firstdawndigital.github.io/Plagg/". `load_from_sheet()` er
  gjort defensiv mod dette (detekterer advarselsrækken, læser header
  fra række 2 i stedet) så den ikke-aktive "sheet"-fallback-vej stadig
  virker korrekt hvis nogen bevidst skifter tilbage. Bekræftet ved at
  læse både advarselscellen og de originale 2 ønsker tilbage fra det
  live ark.
- **J5:** Ny konstant `NON_BUNDLEABLE_SOURCES = {"sellpy"}` i
  `bundling.py` -- kilder her danner ALDRIG en bundle uanset antal
  matches (optræder kun i Matches-listen). Regressionstestet: Reshopper/
  DBA bundler stadig korrekt ved 2+ items, Sellpy danner 0 bundles selv
  ved 3 usammenhængende matches.
- **J6:** Statustekst rettet til "kan tage op til 15 min." i
  `trigger_watcher.py` og `sheets_output.py`s Kontrolpanel-hjælpetekst,
  PLUS den live Sheet-celle (C2) opdateret direkte og læst tilbage som
  bekræftelse.
- **J7:** `sources/sellpy.py`s docstring præciseret -- størrelses-
  udelukkelse gælder kun når ØNSKET selv har en størrelse, ikke en
  generel voksentøjs-garanti (G7-regression). README nævner nu Sellpy
  som tredje kilde konsekvent.
- **TL;DR-flytning:** `#tldr-banner` flyttet til at stå lige efter
  topbar'en (FØR ønskeseddel-sektionen, som selv forbliver først).
  Bekræftet med Playwright (mobil 390×844, 7 ønsker): banner ved y=68px,
  ønskeseddel-sektion starter y=133px -- handl-nu-signalet er synligt
  uden scroll.
- Alle Python-filer bekræftet kompilerende (`py_compile`) inden commit.

**G8 leveret (2026-07-10):** `sources/sellpy.py` bygget efter samme
to-fase-kontrakt som Reshopper/DBA, men `fetch_details()` er no-op (alt
ligger i Algolia-hittet). Ét offentligt Algolia-kald pr. søgeterm, ingen
login/bot-wall. Felter: `price_DK.amount` (øre→kr), `metadata.brand/
size/condition/type`, `isOnShelf`-filter, item-URL `sellpy.dk/item/
<objectID>`. Cm-størrelse parses via regex `CM-(\d+)`, interval "98/104"
→ "98" (første tal — kendt skævhed: undervurderer, gør 98/104 til "nær"
i stedet for "eksakt"). Alt Sellpy-gods grupperes under én "Sellpy"-
sælger (konsignation). Testet live: 37 rå hits → 4 kandidater → 4
matches, medregnet i en rigtig kørsel (run_id=15).

**Bundle-definition strammet (2026-07-10, Esben-ønske):** en bundle
kræver nu 2+ items (`bundling.py` frafiltrerer enkelt-item-sælgere) —
de er stadig i Matches. Retter at bundle-tallet øverst (status/TL;DR)
ikke matchede faktisk antal bundles. Bekræftet: kørsel gav "13 matches,
2 bundles" hvor tidligere samme data viste 5-6 "bundles".

**Mobil-layout-fix (2026-07-10):** webappens ønskeseddel-formular
skubbede på smalle skærme "Slet"-knappen ud over kanten (input's
indbyggede min-bredde). Rettet med `min-width:0` på grid-celler/input +
`overflow-x:hidden` sikkerhedsnet. Bekræftet på 360px viewport: ingen
vandret overflow, knap inden for skærmen.

**G7 leveret (2026-07-10):** størrelse er ikke længere påkrævet.
`matching._size_rank()` returnerer "eksakt" ved tom ønske-størrelse (så
den ikke blokerer eller trækker ned til nær-match), `wishlist.py` kræver
kun type, `worker.js` kun type-validering (deployet), `docs/index.html`
markerer feltet valgfrit og håndterer tom størrelse i validering+visning.
Regressionstestet: tøj med størrelse opfører sig præcis som før (104
eksakt, 98 nær, 80 udelukket). Bekræftet live at et størrelsesløst ønske
(fx "lego duplo") kan tilføjes uden fejl. Baggrund: Esben testede en
Lego-gravko der gav 0 matches -- kodegennemgang viste at fase 1-precheck
hårdt krævede en tøj-størrelse på stigen 50-176, så alt sizeløst blev
filtreret væk.

**G8/G9 (ny 2026-07-10):** Esben ønsker Sellpy + Vinted som EKSTRA
match-kilder -- ikke primært for bundling, men for at ØGE UDBUDDET af
fund og give bedre grundlag for prissammenligning. Bundling valgfri/NA.

Dataadgangs-spike (2026-07-10) bekræftet med rigtige kald, BEGGE uden
login (modsat DBA):
- **Sellpy (G8, Size 3, byg først):** offentligt Algolia-kald `POST
  https://3lxsu2dn7t-dsn.algolia.net/1/indexes/*/queries` (app-id
  `3LXSU2DN7T`, dansk søge-key `380077912d5cdc2bebf67d4b4ad10a30`),
  index `prod_marketItem_da_relevance` (IKKE `_saleStartedAt_desc` --
  det gav solgte varer uden pris). ALT i hittet: `price_DK.amount` (øre,
  /100), `metadata.brand/size/condition/type`, `isOnShelf` (filtrér
  klient-side), item-URL `sellpy.dk/item/<objectID>`. robots.txt
  `Allow: /`, ingen bot-wall. Konsignationsmodel (ingen sælger-bundling).
- **Vinted (G9, Size 4):** anonym cookie-priming (`GET vinted.dk/` →
  cookies) + `GET vinted.dk/api/v2/catalog/items?search_text=<term>` →
  ren JSON. Ingen login. ALT på liste-niveau: `price.amount`,
  `brand_title`, `size_title`, `status` (stand), `user`, `url`.
  robots.txt tillader `/catalog`+`/api/v2` for normal UA (men
  Disallow: / for AI-bots, + ToS-klausuler om "no automated
  transactions" -- samme gråzone som Reshopper/DBA, Esben-godkendt
  tilgang). DataDome-beskyttelse -> skånsom kadence nødvendig.
  Cross-border EU-udbud med DKK-omregnede priser (fragt varierer).

**G6 (ny 2026-07-10):** Ønskesedlens "Stand"-felt (fx "som nyt"/"må
gerne være slidt") er i dag et rent fritekstfelt der IKKE bruges til
matching -- bekræftet ved kodegennemgang af `matching.py`, feltet nævnes
kun i en kommentar, ingen filter-/nedtonings-logik eksisterer. Esben har
bedt om at bevare feltet og bygge rigtig funktionalitet senere (ikke nu):
filtrér/nedton fund hvor annoncens stand tydeligt afviger fra det ønskede
(fx udeluk "defekt" hvis ønsket stand er "som nyt"). Ikke scoret endnu --
kræver et design af "stand-kompatibilitet" (hvilke kombinationer er OK/
ikke-OK), og fortolkning af Reshopper/DBA's egne stand-labels (se
`sources/reshopper.py`/`sources/dba.py`s stand-udtræk).

H-serien (fra demo-kritik) er leveret, se status-tabellen nedenfor. Den laa
foran G-serien (brief §10-idéer) fordi den rettede selve MVP-outputtet og var
billigere/mere presserende end at udvide scope. G-serien er kun groft scoret;
re-scores naar vi kender faktisk brugsmønster over tid.

## Udestående (2026-07-09) — til fælles planlægning

```
Emne                                   Type          Ejer
--------------------------------------  ------------  ------------
G5: aktivér som dagligt dashboard      Beslutning    Esben
  (config-flip til "turso", se G5-status)
G2 -- notifikationer                   Kvalificering Esbens kone
G3 -- beskedudkast/reservation         Kvalificering Esbens kone
G4 -- region-filtrering                Prioritering  Esben
launchd: 2x-dagligt scheduled task     Drift         Esben (godkend)
launchd: trigger_watcher.py            Drift         Esben (godkend)
DBA-session (.dba_storage_state.json)  Kendt risiko  Esben (ved udløb)
```

- **G5:** kode pushet, webapp live på https://firstdawndigital.github.io/Plagg/
  (repo `FirstDawnDigital/Plagg`, gjort offentligt 2026-07-10 for at
  kunne bruge GitHub Pages på org-planen). Eneste resterende skridt er
  Esbens egen beslutning om at aktivere Turso-sporet som det der reelt
  opdateres ved fremtidige kørsler (config-flip, se G5-status).
- **G2/G3:** bevidst ikke bygget — begge kræver at Esbens kone har brugt
  systemet et stykke tid først, så kvalificeringen er baseret på reel
  brug, ikke gæt.
- **G4:** ikke afvist, bare ikke prioriteret af Esben endnu.
- **launchd (begge):** dokumenteret i README.md, bevidst ikke installeret
  — er en systemniveau-ændring der kræver eksplicit godkendelse. Uden
  dem overlever hverken det 2x-dagligt scrape eller Kør nu-trigger'en en
  genstart/session-lukning af Mac'en.
- **DBA-session:** ingen automatisk fornyelse i MVP (bevidst, se G1-fund)
  — når den udløber, stopper `sources/dba.py` gracefully og logger en
  fejl, ikke en crash, men kilden leverer 0 resultater indtil Esben
  gentager manuel-login-trinnet.
- **Git:** lokalt repo er initialiseret (`git init` kørt 2026-07-09 i
  forbindelse med at validere `.gitignore`) men INGEN commits/push er
  lavet endnu — hele kodebasen mangler stadig at komme op på
  `FirstDawnDigital/Plagg`.

### G5-status (2026-07-09): forudsætninger klar, arkitektur ikke lagt endnu

Besluttet: hostet webapp med Turso + Cloudflare Worker + GitHub Pages,
samme mønster som ejendompython-arkivets LIVE opsætning (ikke den
discontinued Render-backend).

**Blokade løst:** `turso auth login`/`wrangler login`/interaktiv OAuth
virker ikke i dette miljø (browser-callback kan ikke fuldføres her,
samme rodårsag som at et headful Playwright-vindue ikke er synligt for
Esben). Løsning fundet: `gh` bruger en device-code-flow der IKKE kræver
lokal browser-callback og virker fint; Turso/Cloudflare bruger i stedet
rene API-tokens (ingen OAuth-session nødvendig).

**Klar til brug (2026-07-09):**
- GitHub: repo oprettet, `FirstDawnDigital/Plagg` (privat). Lokalt
  `git init` kørt i `personal-shopper/` -- IKKE committet/pushet endnu.
- Turso: database `plagg` findes (Esben oprettede den selv), URL +
  access-token ligger i `secrets.env` (IKKE i git, se `.gitignore`).
- Cloudflare: API-token + korrekt Account ID (`6b3cb45c05b6533cc0d1d644b8924df6`,
  hentet automatisk via `wrangler whoami` med tokenet -- den værdi
  Esben først satte ind var fejlagtigt hans e-mail) ligger i `secrets.env`.

**Arkitektur nu designet og godkendt (2026-07-09):** fuld plan i
`/Users/server/.claude/plans/tidy-dreaming-liskov.md` -- Turso-skema
(wishlist/matches/bundles/control med generations-swap i stedet for
DELETE+INSERT), ny fil `turso_io.py` (spejler `sheets_output.py`s rolle),
Cloudflare Worker med 7 X-API-Key-beskyttede endpoints, statisk vanilla-JS
frontend, GitHub Actions-workflow. **Bindende:** Sheets-sporet forbliver
100% intakt og kørende sideløbende under HELE byggeprocessen -- kun et
eksplicit valg af Esben i `config.yaml` (`output.targets`/`trigger.source`)
kan nogensinde slå det fra. Byggerækkefølge: (1) `turso_io.py` isoleret,
(2) Cloudflare Worker, (3) frontend testet lokalt FØR push, (4) dual-write
wiring af monitor.py/trigger_watcher.py sidst.

**Fase 1 leveret (2026-07-09):** `turso_io.py` bygget og testet direkte mod
den ægte `plagg`-database. `ensure_schema()` bekræftet (4 tabeller +
control-singleton oprettet). Generations-swap bekræftet ved 2 på-hinanden-
følgende `write_matches_and_bundles()`-kald med forskelligt testdata: 2.
kørsels data erstattede 1. kørsels fuldstændigt (`SELECT DISTINCT run_id`
gav kun den nyeste), ingen sammenblanding. Kør nu-flow
(`read_run_now`/`set_status`/`finish_run`) testet og bekræftet. Testdata
ryddet op efter -- databasen står jomfruelig tilbage. Ikke testet: reel
samtidighed (to overlappende write-kald) -- kun sekventielt.

**Fase 2 leveret (2026-07-09):** `cloudflare/worker.js`+`wrangler.toml`
bygget, deployet ikke-interaktivt (API-token, intet `wrangler login`) til
**https://plagg-api.proqual.workers.dev**. Secrets sat (`TURSO_URL`,
`TURSO_AUTH_TOKEN`, `API_KEY=klematis`). Alle 7 endpoints bekræftet med
curl: wishlist-CRUD (opret→list→slet→bekræft væk), matches/bundles (tom
liste, korrekt), status/trigger (run_now 0→1 bekræftet), og en EKSPLICIT
401 uden `X-API-Key`-header. Kendt detalje: ~10-15 sek. propagerings-
forsinkelse observeret lige efter `wrangler secret put`, ingen retry-logik
tilføjet (ikke nødvendigt post-deploy). Test-triggeren (`run_now=1`)
nulstillet af mig bagefter for at holde databasen ren før Fase 4.

**Fase 3 leveret (2026-07-09):** `docs/index.html` bygget (vanilla JS, ingen
build-step) og testet med Playwright i mobil viewport (390×844) mod den
LIVE Worker. Password-flow, wishlist-CRUD, og Kør nu+statuspolling alle
bekræftet virkende. Kritik-runde ("Esbens kone"-persona, samme metode som
H-serien) fandt 5 problemer, 4+1 rettet med det samme:
- Tomt/ugyldigt maks-pris-felt endte tidligere stille som "ingen
  prisgrænse" -- undersøgt og bekræftet at `maks_pris=0` reelt betyder
  "udelukker ALT" i `matching.py` (`price > maks_pris`-filter), ikke
  "ingen grænse". Feltet er nu påkrævet med synlig fejl.
- "Kør nu" viste kun en misvisende 3-sekunders knap-deaktivering (ikke
  reel status) -- tilføjet et vedvarende bekræftelsesbanner uafhængigt
  af knappens animation, med 20s timeout-advarsel hvis ingen kørsel
  reelt starter (relevant før Fase 4 er koblet til).
- Brugerdefineret fejltekst for manglende felter blev aldrig vist,
  fordi HTML5 `required`-native-validering blokerede submit først --
  fjernet `required`, al validering går nu gennem app-koden.
- Sletning af ønskeseddel-item manglede bekræftelse -- tilføjet
  `confirm()`-dialog.
- (Bonus) Slet-knappens tap-target forstørret til 44px min.
Pushet til GitHub 2026-07-10 efter Fase 4 + kritikrunde var færdig,
som planlagt.

**Fase 4 leveret (2026-07-10):** `config.yaml` (nye additive `turso:`/
`output:`-sektioner + `trigger.source`), `monitor.py` (Turso-skema
bekræftes i samme try/except som Sheets, output-skrivning er nu en
løkke over `output.targets` med Turso i sit eget try/except),
`trigger_watcher.py` (backend-adapter `SheetsControlBackend`/
`TursoControlBackend`, loop-logik uændret), `wishlist.py` (ny
`source: "turso"`-gren, samme fallback-mønster som `"sheet"`).

**Ærlig hændelse undervejs:** byggeagentens egen dual-write-testkørsel
hang natten over (sidste log-linje kl. 00:24, ingen `monitor.py`-proces
kørende ved tjek kl. 08:46, Turso stadig 100% upåvirket) -- formentlig et
forbigående Reshopper/Playwright-netværksudsving, IKKE en kodefejl (koden
blev læst igennem og matcher planen præcist). Jeg reproducerede og
verificerede derfor Fase 4 SELV i forgrunden i stedet for at stole på
agentens ubekræftede rapport:
- **Regressionstest:** ikke eksplicit gen-kørt isoleret (implicit
  bekræftet af dual-write-testen nedenfor, som også skriver til Sheets
  uændret).
- **Dual-write, kørsel 1:** `output.targets: ["sheet","turso"]`, rigtig
  scraping (12 matches, 5 bundles) -- Sheets opdateret OG Turso
  bekræftet via direkte SELECT (`matches`=12, `bundles`=5,
  `current_run_id`=1, `last_tldr` matcher Sheets' TL;DR ordret).
- **Dual-write, kørsel 2 (generations-swap over ægte data):** kørt igen
  umiddelbart efter -- `current_run_id`=2, `SELECT DISTINCT run_id FROM
  matches` gav KUN `{2}` (12 rækker, ikke 24) -- gen1 korrekt erstattet,
  ikke akkumuleret.
- **Trigger-backend (Turso):** `trigger.source: "turso"` midlertidigt
  sat, `run_now=1` sat direkte i Turso, `python trigger_watcher.py
  --once` kørt -- detekterede korrekt, kørte en fuld `monitor.py`-
  kørsel (run_id=3), og nulstillede `run_now=0` +
  `status="Færdig kl. 08:59 (12 matches, 5 bundles)"` i Turso.
- **Config.yaml sat tilbage** til sikre defaults (`output.targets:
  ["sheet"]`, `trigger.source: "sheet"`, `wishlist.source: "sheet"`
  uændret) efter test -- bekræftet ved grep.

**Sikkerhedsfund (rettet med det samme):** en efterladt fil `.env.save`
med et rigtigt Cloudflare API-token i klartekst lå i personal-shopper/,
IKKE dækket af `.gitignore` (kun `secrets.env` var). Formentlig et
biprodukt fra Fase 2's `wrangler secret put`-arbejde. Slettet øjeblikkeligt
ved opdagelse, før noget nåede i nærheden af et git-commit.

**Teknisk fejl-gennemgang efter Fase 4 (2026-07-10)** — uafhængig code
review (ikke UX-kritik, ren korrekthed) fandt 5 problemer, 4 rettet med
det samme:
- **KRITISK:** `monitor.py` havde Sheets- og Turso-opsætning i SAMME
  try/except -- en Sheets-fejl (fx forkert credentials-sti) sprang
  derfor Turso-load'et helt over pga. Pythons try/except-semantik,
  selvom de to er uafhængige. Rettet: to separate try/except-blokke.
- **KRITISK:** Race condition i `turso_io.py`s generations-swap kunne
  slette en ANDEN, samtidig kørsels data -- "best-effort oprydning"
  slettede alt der ikke matchede det globalt nyeste `current_run_id`,
  hvilket kunne ramme en hurtigere sideløbende kørsels allerede-
  indsatte-men-endnu-ikke-publicerede rækker. Rettet: hver skriver
  rydder nu KUN op i den specifikke generation den selv erstattede
  (`superseded_run_id`, læst FØR eget run_id allokeres), aldrig et
  bredt "alt andet end nyeste"-slet. Reproduceret og bekræftet rettet
  med den præcise overlap-rækkefølge fra reviewet.
- **MODERAT:** `worker.js` validerede ikke `maks_pris` server-side --
  ugyldig/negativ værdi endte som en rå, lækket Turso-500-fejl. Rettet:
  klar 400-validering (positivt tal, ikke-tomme type/størrelse) FØR
  Turso-kaldet.
- **LAV men vigtigt:** hvis ALLE kilder fejlede (fx total netværksfejl),
  saa generations-swap identisk ud som "markedet har reelt 0 nye
  matches" og slettede al eksisterende data. Rettet: `run_source()`
  returnerer nu ogsaa en success-status; hvis ALLE kilder fejlede
  springes HELE output-skrivningen (Sheets+Turso+CSV) over for den
  koersel, med en tydelig advarsel i stedet.
- (Ikke rettet, lav prioritet:) `DELETE /api/wishlist/:id` med et
  ikke-numerisk ID giver en generisk 404 i stedet for en klar 400 --
  ingen sikkerhedsrisiko (SQL-injection udelukket ved test), kun en
  mindre tydelig fejlbesked.

Alle 4 rettelser testet konkret mod den ægte Turso-database og live
Worker (inkl. en direkte reproduktion af race-scenariet og en monkeypatch-
test af "alle kilder fejler"-stien via en rigtig `monitor.main()`-kørsel).
`config.yaml` bekræftet tilbage til sikre defaults efter alt testarbejde.

**G5 er nu funktionelt komplet, teknisk gennemgået OG LIVE (2026-07-10):**
kode pushet til `FirstDawnDigital/Plagg` (Esben gav eksplicit ok), repo
gjort offentligt (org-planen understøtter ikke Pages fra private repos --
ingen hemmeligheder i koden), GitHub Pages aktiveret (servér fra
`main`/`docs`, ingen Actions-workflow nødvendig da frontend er ren
statisk HTML uden build-step). Bekræftet live med Playwright:
**https://firstdawndigital.github.io/Plagg/**, login "klematis" virker,
viser korrekt data fra Fase 4-testkørslerne. Eneste resterende skridt:
Esbens beslutning om at flippe `output.targets`/`trigger.source`/
`wishlist.source` til `"turso"` i `config.yaml`, saa fremtidige kørsler
rent faktisk opdaterer webappen (indtil da viser den i morges' testdata,
uændret, harmløst).

### G1-fund (2026-07-09): login løser bundling-problemet

F1-lignende spike viste at DBA's sælgernavn/-profil er login-låst for
anonyme klienter, og at Sellpy er en konsignationsmodel (fælles fragt på
tværs af HELE markedet, ikke pr. sælger) — se tidligere fund. Esben
besluttede at gå videre med **login via en NY, dedikeret DBA-konto**
(ikke en privat/rigtig konto — isolerer risikoen hvis kontoen skulle
blive spærret), oprettet med `firstdawndigital@gmail.com`.

**Vigtigt delfund:** DBA/Vend-loginet har en Google reCAPTCHA på selve
login-siden — kan ikke løses af automatiseret Playwright (bevidst
undladt, det ville være automatiseret detektionsomgåelse). Løsning:
Esben loggede ind MANUELT i sin egen browser (ingen automatisering),
eksporterede cookies via browser-udvidelsen "Cookie-Editor", og delte
JSON'en. Cookies blev konverteret til Playwright `storage_state`-format
og gemt i `.dba_storage_state.json` (IKKE i git, se `.gitignore`).

**Bekræftet virkende (2026-07-09, screenshot-verificeret):** en
Playwright-context der loader `.dba_storage_state.json` viser login-only
navigation ("Beskeder", "Min DBA") OG en tidligere låst sælgersektion på
en annonceside — sælgernavn ("Nicoline A"), MitID-validering, "På DBA
siden 2011", rating. Bundling pr. sælger er dermed teknisk muligt.

**URL-mønstre fundet:** søgning `https://www.dba.dk/recommerce/forsale/search?q=<term>`,
annonceside `https://www.dba.dk/recommerce/forsale/item/<id>` (IKKE
`/item/<id>` alene, som en tidligere antagelse fejlagtigt brugte).
JSON-LD (`Product`/`Offer`) på annoncesiden har pris/mærke/stand/størrelse
men INTET sælgerfelt — sælgernavn skal hentes fra det renderede DOM
(kræver fuld JS-rendering, ikke kun `domcontentloaded`+kort sleep — se
byggeagentens research for korrekt selector/ventestrategi).

**Session-vedligehold (kendt begrænsning):** cookien er en engangs-eksport
fra Esbens login 2026-07-09 — udløber efter ukendt tid (typisk uger til
måneder for denne slags sessions). Når den udløber, skal Esben gentage
manuel-login-+-cookie-export-trinnet. Ingen automatisk fornyelse i MVP.

### Status på G-serien

```
ID    Emne                              Dato        Status
----  --------------------------------  ----------  --------
G1    DBA som ny kilde (MED bundling)   2026-07-09  DONE
```

### G1-levering (2026-07-09): `sources/dba.py` bygget og testet mod live data

Ny kilde `sources/dba.py` følger PRÆCIS samme to-fase-kontrakt som
`sources/reshopper.py` (`fetch()` → kort-niveau via `search?q=<term>`,
`matching.precheck()` filtrerer billigt, `fetch_details()` besøger KUN
kandidater) — `monitor.py`/`matching.py`/`bundling.py`/`sheets_output.py`
genbruges UÆNDREDE bortset fra de to rettelser nedenfor. Wiret ind i
`monitor.py` via `SOURCE_MODULES = {"reshopper": ..., "dba": ...}`; den
gamle Reshopper-specifikke `run_reshopper()` er omdøbt/generaliseret til
`run_source(source_name, source_module, ...)` da fase 1/2-logikken var
identisk på tværs af kilder.

**Uventet DOM-fund (afgørende for hele designet):** DBA er bygget som en
Schibsted/Vend "Podium"-mikrofrontend med webkomponenter i **shadow DOM**
(fx `<finn-topbar>`). Både `page.content()` og
`document.body.innerText`/`textContent` gav uventet TOMT resultat på
annoncesidens sælgersektion, selvom et screenshot viste indholdet tydeligt
— fordi hverken Playwrights `page.content()` (kun light DOM) eller native
`document.querySelectorAll` (piercer ikke shadow-root) når ind i et
shadow-root. Kun Playwrights EGNE `locator()`/`query_selector_all()`-kald
(som piercer shadow-DOM som standard for CSS-selectors) eller en
JS-`evaluate` der eksplicit traverserer `element.shadowRoot` virker.

**Bedre fund end DOM-scanning:** annoncesiden indeholder et `<script>`
(inde i et shadow-root) med `window.__staticRouterHydrationData =
JSON.parse("...")` — en SERVER-renderet JSON-blob med sælgernavn
(`profileData.profile.identity.name`), en STABIL numerisk sælger-ID
(`itemData.meta.ownerId` — mere pålidelig end Reshoppers best-effort
regex-udtræk), fragttekst ("Fragt fra 29,99 kr. + ...") og en præcis
dansk stand-label via `extras`-listen (`id="condition"`, label "Stand").
Dette er den PRIMÆRE kilde til sælger/fragt/stand; JSON-LD
(`application/ld+json`, samme schema.org-mønster som Reshopper) bruges
som fallback for pris/mærke/stand hvis hydration-JSON'en fejler at parse
(uofficiel struktur, kan brække ved et DBA-redeploy — graceful
degradation til "ukendt"/`None`, aldrig en crash).

**Bundling-fix (grundlæggende korrekthed, ikke kun DBA-specifik):**
`bundling.py:_seller_key()` grupperede FØR denne ændring KUN på
sælger-ID/-navn, uden kilde — en Reshopper-sælger og en DBA-sælger med
samme navn (eller ved et sammentræf samme numeriske ID) ville fejlagtigt
blive slået sammen til én bundle. Nøglen præfikses nu altid med kilden
(`f"{source}|id:{seller_id}"`). `sheets_output.py` fik en ny "Kilde"-
kolonne i både Matches- og Bundles-fanerne (og CSV-fallback) af samme
grund — med to platforme side om side er det ikke længere indlysende
hvilken platform et opslag/en bundle stammer fra.

**Session-håndtering:** `sources/dba.py` forsøger ALDRIG selv at logge
ind, løse CAPTCHA eller forny `.dba_storage_state.json`. Et
`_session_looks_logged_in()`-tjek (Playwright-locator for
`a[href*="/my-page"], a[href*="/messages"]` — bevidst IKKE
`page.content()`, som ikke ser ind i shadow-DOM'en de linkene faktisk
ligger i) kører én gang pr. kørsel; ser sessionen udløbet ud, stopper
kilden og logger en fejl der eksplicit beder om at eskalere til Esben.

**Bekræftet ved LIVE kørsler 2026-07-09 (ikke kun `--dry-run`):**
- `python monitor.py --dry-run --source dba` mod ønskesedlens 2 test-items
  (Birkholm leggings 104, Zara bukser 104): 20 rå annoncer hentet (10 pr.
  søgeterm), 0 kandidater efter `precheck()` — reelt (ægte markedsdata
  lige nu har ingen Birkholm-leggings eller Zara-bukser i str. 104 blandt
  DBA's top-10 søgeresultater for de PRÆCISE ønskeseddel-afledte termer),
  ikke en fejl. Samme kendte "kun ~10 kort, ingen bekræftet 'vis flere'"-
  begrænsning som Reshopper (se F2-fund) gør sig gældende for DBA.
- For at bevise at hele kæden (fetch_details → matching → bundling)
  RENT FAKTISK virker mod ægte DBA-data, blev en bredere søgning
  ("Zara bukser 104") brugt til manuelt at finde et ægte, levende DBA-
  opslag der matcher testkriterierne: vare-ID 838456 →
  "Bukser, Vinter, Zara", str. 104, 150 kr. `fetch_details()` +
  `matching.match_item()` + `bundling.build_bundles()` kørt direkte mod
  denne URL bekræftede: sælgernavn "Annette L", sælger-ID "1402936400"
  (hydration-udtræk lykkedes), match_rank "nær match" (mærkefelt manglede
  i denne annonces JSON-LD, faldt korrekt tilbage til nær-match via det
  generiske mærke-spor), bundle med `shipping_is_assumed=True` (39 kr.
  fallback, ingen fragt-tekst fundet for netop denne annonce) — al
  graceful degradation opførte sig som designet.
- Fuld produktionskørsel `python monitor.py` (begge kilder, IKKE
  `--dry-run`, skriver til det rigtige Sheet): Reshopper gav 11 matches/
  4 bundles, DBA gav 0 (samme top-10-søgeterm-begrænsning som ovenfor for
  netop denne kørsels tidspunkt). Matches- og Bundles-fanerne blev
  bekræftet at have den nye "Kilde"-kolonne med værdien "Reshopper"
  korrekt udfyldt ved direkte genlæsning af arket via `gspread`.

**Kendte usikkerheder/skrøbeligheder (ærligt flaget):**
- Sælgernavn/-ID/fragt/stand afhænger af den udokumenterede
  `__staticRouterHydrationData`-struktur — kan brække ved et DBA/Vend-
  redeploy (samme risikoklasse som Reshoppers sælger-ID-udtræk).
  Graceful fallback til JSON-LD/"ukendt" er på plads, men ikke testet
  mod en fremtidig strukturændring (kan ikke være det, per definition).
- Fragt-udtræk (`_parse_kr_amount` på hydration-JSON'ens
  `shippingPrice.text`) er kun bekræftet på ÉN reel annonce med udfyldt
  fragttekst ("Fragt fra 29,99 kr. + Tryg betaling 11 kr.") — ikke
  bredt valideret mod annoncer uden Fiks færdig/andre fragtmodeller.
- `max_results_per_term: 10` er samme antagelse som Reshopper (ingen
  "vis flere"-trigger undersøgt for DBA) — betyder reelt at DBA-fund kan
  mangle hvis et match ligger uden for de første 10 søgeresultater, som
  set i denne kørsel.

## Status på oprindelig MVP-build (alt leveret)

```
ID    Emne                              Dato        Status
----  --------------------------------  ----------  --------
F1    Reshopper dataadgang-spike        2026-07-08  DONE
F2    Dataindsamling -> item-model      2026-07-09  DONE
F3    Ønskeseddel + matching            2026-07-09  DONE
F4    Bundling pr. sælger               2026-07-09  DONE
F5    Output til dashboard-Sheet        2026-07-09  DONE (*, LIVE)
F6    Scheduled task (2x/dag)           2026-07-09  DONE (**)
F7    Validering mod 2 test-items       2026-07-09  DONE
```
(*, LIVE) Sheets-auto-oprettelse fejlede pga. servicekontoens manglende
Drive-kvote — krævede ét manuelt trin (menneske opretter Sheet, deler det
MED servicekontoen). Esben delte et Sheet og satte ID i `config.yaml`
2026-07-09 — pipeline kørt og BEKRÆFTET at skrive live til "Matches"- og
"Bundles"-faner (se link øverst i filen). CSV-fallback ikke længere i brug.
(**) launchd-plist dokumenteret i README.md, bevidst ikke installeret.

**Byggerækkefølge (afhængighedsstyret, ikke ren WSJF):** F1→F2→F3→F4→F5→F6→F7

## Status på demo-kritik-rettelser (H-serien, alt leveret)

```
ID    Emne                              Dato        Status
----  --------------------------------  ----------  --------
H1    Bundle-links direkte i output     2026-07-09  DONE
H2    TL;DR "hvad betaler sig nu"       2026-07-09  DONE
H3    Nedton/flag defekte items         2026-07-09  DONE
H4    Afklar dubletter i output         2026-07-09  DONE
H5    Kr.-enhed + JA/NEJ-konsistens     2026-07-09  DONE
I1    Trigger-fra-Sheet (kør nu)       2026-07-09  DONE
```

## Status på kritik-loop 2 (Kontrolpanel + ønskeseddel-flow)

```
ID    Emne                              Dato        Status
----  --------------------------------  ----------  --------
J1    Kortere poll + ventetids-hint     2026-07-09  DONE
J2    Varsel ved sprunget ønske-række   2026-07-09  DONE
J3    Visuel "kørsel i gang"-lås        2026-07-09  DONE
```

Rollespil mod det ægte ark (samme "travl kone"-persona som H-serien) fandt:
op til 60 sek. stilhed efter klik uden feedback var den reelle risiko (hun
ville tro klikket ikke registrerede) — **J1** sætter `poll_interval_s` 60→15
og tilføjer et "kan tage op til 15 sek./typisk 1-3 min."-hint i Kontrolpanel-
teksten og Status-beskeden. **J2:** en ønskeseddel-række med indhold men
manglende Type/Størrelse (fx tastefejl) forsvandt tidligere stille — nu
logges `SKIPPED_WISHLIST_ROWS=N` i `wishlist.py`, opfanget af
`trigger_watcher.py` og tilføjet til Status som "OBS: N ønske sprunget
over, tjek Ønskeseddel-fanen". Begge testet live: J2 bekræftet ved
midlertidigt at tilføje en ugyldig raekke (Type="sweater", Størrelse tom) —
gav korrekt `SKIPPED_WISHLIST_ROWS=1` og lod de 2 gyldige items passere
uændret; raekken fjernet igen efter test.

Et fjerde kritikpunkt (ingen visuel "kørsel i gang"-lås på selve checkboxen)
blev efterfølgende også bygget: selvom et gen-klik under en kørsel er
ufarligt (watcheren er synkron), manglede der en tydelig VISUEL indikation
ud over Status-teksten alene. **J3:** `sheets_output.lock_control_row()`
sætter en gul-orange baggrund (`CONTROL_RUNNING_BG`) på "Kør nu"- og
Status-rækken (A2:D3), kaldt af `trigger_watcher.py` lige efter
Status="Kører..." sættes. `finish_run()` nulstiller den samme baggrund til
hvid (`CONTROL_NORMAL_BG`) igen, så laasen altid fjernes uanset succes/fejl
— samme funktion der allerede nulstiller checkbox/Status/Sidst kørt.
Testet ved at simulere start/slut direkte via `sheets_output`-funktionerne
(uden at vente på en rigtig 2-3 min. kørsel) og læse cellernes
`userEnteredFormat.backgroundColor` tilbage fra Sheets-API'en: under
kørsel gav A2:D3 `{red:1, green:0.898, blue:0.6}` (matcher
`CONTROL_RUNNING_BG`), efter `finish_run()` gav samme celler `{red:1,
green:1, blue:1}` (hvid/normal) — og B2/B3/B4 var korrekt nulstillet.

## Afklarede spørgsmål/beslutninger

- **Google Sheets-adgang:** genbruger service account fra ejendompython-
  arkivet: `ejendom-server@ejendomsystem-493221.iam.gserviceaccount.com`
  (afklaret 2026-07-08).
- **Scraping vs. robots.txt:** Reshoppers `robots.txt` spærrer eksplicit
  generiske bots. Besluttet at bygge alligevel, lavfrekvent/skånsomt, samme
  gråzone-tilgang som Blocket/Kleinanzeigen i PA SPEAKERS-arkivet (afklaret
  2026-07-08).
- **Brief §6-eksempel er unøjagtigt:** "4×20 kr + 45 kr fragt = 26 kr/stk"
  går ikke matematisk op (giver 31,25 kr/stk) — bekræftet under test at
  koden selv regner korrekt, det var brief-eksemplet der var upræcist.
  Ret ved lejlighed i personal-shopper-brief.md, ikke i koden.

## Scoring-detaljer (F-serie)

```
F1  Reshopper dataadgang-spike
    BV 8  TC 8  RR 9  CoD 25  Size 2  WSJF 12.5
F2  Dataindsamling → normaliseret item-model
    BV 9  TC 7  RR 6  CoD 22  Size 6  WSJF 3.7
    Size opjusteret 5→6 efter F1: client-renderet søgeflow + 429-håndtering.
F3  Ønskeseddel-input + matching-logik
    BV 9  TC 6  RR 4  CoD 19  Size 4  WSJF 4.75
F4  Bundling-beregning pr. sælger
    BV 10 TC 5  RR 3  CoD 18  Size 3  WSJF 6.0
F5  Output til dashboard-Sheet
    BV 7  TC 5  RR 2  CoD 14  Size 3  WSJF 4.7
F6  Scheduled task (2x dagligt)
    BV 5  TC 3  RR 2  CoD 10  Size 2  WSJF 5.0
F7  Validering mod 2 test-items
    BV 6  TC 6  RR 3  CoD 15  Size 2  WSJF 7.5
```

Begrundelse (kort): F1 højest da hele arkitekturen afhang af svaret (lavt
Size = ren spike). F4 har højeste BV (selve fragt-økonomi-værdiforslaget),
men kan først bygges når F3 leverer data at gruppere. F7 scorer højt
isoleret, men giver kun mening som sidste led. Genbrug fra `CC ARCHIVE`
(monitor.py, sources/*.py, db.py, sheets_exporter.py) sænkede Size markant
på F2/F5/F6 — intet af det blev bygget fra bunden.

## F1-fund (styrer resten af build)

- Reshopper (`reshopper.com`) er en Next.js-SPA bag Vercels bot-management.
  `curl`/simple HTTP 429'er med `x-vercel-mitigated: challenge`, men en
  rigtig Playwright-Chromium fik 200 på forsiden. Intet API fundet.
- `robots.txt`: `Disallow: /` for `User-Agent: *`, allow-lister kun
  navngivne søgemaskine-bots — eksplicit "vil ikke scrapes"-signal.
- Bot-wall-detektion tjekker **429 + `x-vercel-mitigated`** som primær-
  signal, danske tekstmarkører som fallback.
- Ved genbesøg under F2-build viste `?q=<term>`-URL'en (som F1 afviste)
  sig rent faktisk at filtrere resultater — bekræftet empirisk ("birkholm"
  → 2.256 varer, opdigtet ord → 0). F2 blev derfor bygget om direkte
  navigation til denne URL, simplere end at simulere klik i søgefeltet.

## Demo-kritik (2026-07-09) — detaljer bag H-serien

Rollespil mod de rigtige CSV-fallback-filer fra F7-validering, i rollen som
Esbens kone: travl, vil have et hurtigt "skal jeg handle nu?"-svar.

- **H1:** Skal i dag krydsreferere `bundles_fallback.csv` mod
  `matches_fallback.csv` for at finde et opslags link — to opslag pr. bundle.
- **H2:** Intet samlet "handl nu"-signal øverst — skal selv regne ud at
  Michelle A og Elisabeth O er de bundles der betaler sig.
- **H3:** "Defekt, kan laves" (Nina S) stod visuelt lige med "Næsten som
  ny" — bør flages tydeligt.
- **H4:** To Michelle A-rækker med identisk pris/stand lignede ved første
  øjekast en duplikat-bug (var reelt to forskellige opslag).
- **H5:** Fragt-kolonne uden enhed ("35"), inkonsistent JA/nej-case.

## Leverance-detaljer (MVP)

**F2:** To-fase-design: `fetch()` henter kort-niveau-data via regex på
`inner_text()` (robust mod Tailwind-churn), `matching.precheck()` filtrerer
billigt FØR detalje-opslag, `fetch_details()` besøger kun kandidater og
læser mærke/stand/sælger/fragt fra `application/ld+json` (schema.org).
Testet 2026-07-09: 20 rå annoncer → 8 kandidater → 8/8 detalje-opslag OK.

**F3:** To-tier ranking (eksakt/nær match), synonymliste for typer, nabo-
størrelsesstige for EU-børnetøj. Ønskeseddel fra Sheet-fane ELLER lokal
`data/wishlist.local.yaml` (de to officielle testposter). Maks-pris 150 kr.
var ikke givet i briefen — sat af bygge-agenten som demo-grænse.

**F4:** Testet mod live data: Michelle A (2× Birkholm leggings) og
Elisabeth O (2× Zara bukser) — begge 17,50 kr./stk. besparelse ved
bundling. Bekræfter kerneværdiforslaget på ægte markedsdata.

**F5:** `client.create()` fejler forudsigeligt (403, 0 Drive-kvote på
servicekontoen — Google-begrænsning, ikke kodefejl). Skrive-mekanikken
(add_worksheet/update/format) er bekræftet mod et allerede delt ark.
Falder automatisk tilbage til CSV indtil Sheet-ID er konfigureret.

**F6:** launchd-plist dokumenteret (kl. 8 og 20), bevidst ikke installeret.

**F7:** Kørt 2026-07-09 mod ægte Reshopper-data (ikke kun `--dry-run`):
8 matches, 6 sælger-grupper, korrekt eksakt/nær-match-ranking, `seen.db`-
dedup bekræftet stabil på tværs af to kørsler.

**Kendte begrænsninger:** kun ~10 kort/søgeterm (ingen bekræftet "vis
flere"), ingen "nyeste først"-sortering, sælger-ID/fragt er best-effort,
ingen aktiv/solgt-tracking.

**H1:** Bundles-fanen har nu dynamiske "Opslag N"-kolonner (én pr. item i
den størst observerede bundle denne kørsel), hver med en klikbar
HYPERLINK-formel direkte til opslaget. CSV-fallback faar samme kolonner
med rå URL'er (CSV kan ikke rumme formler). Bekræftet ved at læse
Bundles-fanen tilbage med value_render_option="FORMULA": Michelle A-
rækken indeholder to virkende =HYPERLINK(...)-formler til de to Birkholm-
leggings-opslag, ingen opslag i Matches-fanen nødvendigt.

**H2:** Bundles-fanen (og CSV'en) starter nu med en dynamisk TL;DR-linje
(sammenlagt/mergeet A1:sidste kolonne), genereret af
`sheets_output.build_tldr_line()` ud fra hvilke bundles der reelt har
`bundle_worth_it=True` denne kørsel. Bekræftet: kørsel mod ægte data gav
"🟢 2 bundle(s) betaler sig lige nu: Michelle A, Elisabeth O" i række 1,
header rykket til række 2, freeze udvidet til 2 rækker.

**H3:** Matches-fanen prefixer nu "⚠️ " foran stand-labels i
`BAD_STAND_LABELS` (pt. kun "Defekt, kan laves" -- de øvrige kendte
labels fra sources/reshopper.py er reelt fint brugbar stand). Rækken faar
desuden en lyserød baggrundsfarve via `ws.batch_format()`. Bekræftet ved
at læse cellens `userEnteredFormat.backgroundColor` tilbage fra Sheets-
API'en for Nina S' "Defekt, kan laves"-række: {red 0.976, green 0.847,
blue 0.820} -- matcher `STAND_WARNING_BG` præcist.

**H4:** To uafhængige tiltag: (1) Matches-fanen fik en ny "Opslag-ID"-
kolonne med de sidste 6 tegn af item-ID'et (fx "…53e1d4" vs. "…26d861"
for de to Michelle A-rækker). (2) Bundles' "Varer i bundle"-tekst
nummererer nu ens-udseende titler inden for samme bundle ("Birkholm
Leggings #1"/"#2"). Begge bekræftet i det faktiske Sheets-output.

**H5:** Fragt vises nu som fx "35 kr." (`sheets_output._format_kr()`) i
både Matches' og Bundles' fragt-kolonner, i stedet for et enhedsløst
tal. "Bundling betaler sig" viser konsekvent "JA"/"NEJ" (fjernet den
tidligere blandede "nej (kun 1 item)"/"JA"-case) -- "Lokal
afhentning-bonus" er samtidig ensrettet til samme JA/NEJ-mønster i
stedet for tom celle/tekst-blanding, for konsistensens skyld.

**I1:** Ny fane "Kontrolpanel" (`sheets_output.ensure_control_tab()`) med en
RIGTIG Sheets-checkbox i B2 -- gspread 6.1.2/6.2.1 (installeret version,
bekræftet) har ingen `insert_checkboxes()`-metode, saa checkboxen bygges
direkte som en `setDataValidation`-request (condition type `BOOLEAN`, tomme
`values`) via `spreadsheet.batch_update()`. Ny fil `trigger_watcher.py`
poller KUN checkbox-cellen (ét `ws.acell()`-kald pr. runde, ikke hele
arket) hvert `trigger.poll_interval_s` sekund (config.yaml, standard 60s),
og trigger ved sandt en fuld `monitor.py`-koersel som adskilt subprocess
(renere end at kalde `monitor.main()` in-process pga. Playwrights
asyncio-loop + gentagne logging-handlers). Fanger alle exceptions fra selve
koerslen saa watcheren aldrig doer af det; SIGINT/SIGTERM haandteres saa
Ctrl+C/`launchctl stop` stopper loopet paent i stedet for midt i en koersel.

Testet direkte mod det live spreadsheet 2026-07-09: satte B2=TRUE via
gspread → `trigger_watcher.py --once` opdagede det og satte Status til
"Kører..." mens en RIGTIG `monitor.py`-subprocess koerte (bekræftet med
`ps aux` mens den koerte) → koerslen fandt 7 matches/5 bundles og skrev dem
til Matches/Bundles-fanerne → Status blev "Færdig kl. 07:47 (7 matches, 5
bundles)", "Sidst kørt" blev "09-07-2026 07:47", og B2 blev nulstillet til
FALSE (`read_run_now()` bekræftet False bagefter). SIGTERM-test af det
kontinuerlige loop (`--poll-interval-s 5`) bekræftede paent stop indenfor
~1 sekund. launchd `KeepAlive`-eksempel (adskilt fra `monitor.py`'s
`StartCalendarInterval`-eksempel) dokumenteret i README.md, bevidst ikke
installeret. Begraensning: koer ikke en manuel `monitor.py`-koersel samtidig
med at watcheren har trigget én -- begge deler `seen.db`/samme Sheet-faner,
ingen laasning mellem processerne pt. (dokumenteret i README.md).

**CSV-fallback:** `write_local_csv_fallback()` genbruger nøjagtig de
samme hjælpefunktioner (`_format_kr`, `_display_stand`, `_items_summary`,
`_short_item_ref`, `build_tldr_line`, `_bundles_header`) som Sheets-
skrivningen, så CSV'en ikke kan drive ud af sync med Sheets-outputtet.
Bekræftet ved direkte kald mod fulde 7-match/5-bundle-datasættet fra den
seneste live-kørsel -- identisk indhold i begge outputs.

## Vedligeholdelse af denne fil

1. Ny idé → tilføj som næste H/G-nummer i den aktive tabel øverst.
2. Påbegyndt → Status: IN PROGRESS. Leveret → flyt til status-tabellen
   med dato, tilføj evt. detaljer i "Leverance-detaljer".
3. Re-scor når forudsætninger ændrer sig — notér i git/commit hvis
   versioneret.
