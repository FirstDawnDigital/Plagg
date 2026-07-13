# BACKLOG — Personal Shopper (branch: Brugt børnetøj / Reshopper)

> Fastbredde-tabeller i kodeblokke (ikke markdown-pipe-tabeller) så filen kan
> monitoreres med `cat`/`watch` i en smal tmux-pane uden at ombrydes grimt.
> Hold linjer under ~70 tegn ved redigering. WSJF = CoD / Size, CoD = BV+TC+RR
> (hver 1–10). Fuld kontekst: se [personal-shopper-brief.md](../personal-shopper-brief.md)

**Live demo/dashboard (aktivt i brug):** https://docs.google.com/spreadsheets/d/1EjCrvQmHcTz6MAhSYhQYPCfbB9rTKyscMJJ5ZtNPjO4
(faner "Matches" og "Bundles", opdateret 2026-07-09 — H1-H5 leveret, se nedenfor)

**G5-webapp (live OG koblet til friske kørsler):** https://firstdawndigital.github.io/Plagg/
(adgangskode "klematis"). Kode pushet til `FirstDawnDigital/Plagg` (repo
gjort offentligt 2026-07-10, da org-planen ikke understøtter Pages fra
private repos -- ingen hemmeligheder i koden, data ligger i Turso, ikke
i repoet). `wishlist.source: "turso"` + en dedikeret
`trigger_watcher.py --source turso`-proces koerer parallelt med
Sheets-sporet -- "Kør nu" i webappen trigger reelle koersler (bekraeftet
live 2026-07-10/11, flere koersler om dagen, 14-25 matches typisk).

## Aktiv backlog (næste øverst)

**To spor, samlet 2026-07-13.** TEKNISK spor (G23-G29, hærdning ift.
`scraper-boilerplate`-evalueringen + sti-flytningens fund) køres først,
som Esben eksplicit bad om. BUSINESS-spor (G30 + G2-G4) er de features
der reelt gør systemet mere nyttigt for Esbens kone i hverdagen -- tages
op igen når det tekniske spor er landet, eller når Esben aktivt
omprioriterer.

```
ID    Emne                              Prioritet     Status
----  --------------------------------  ------------  --------
      TEKNISK SPOR (køres nu)
G23   Sti-flytning (~/CC/) + trigger-   Size 3        DONE
      watcher launchd-konsolidering
G24   Healthcheck-ping (healthchecks.io)Size 1        NÆSTE
G25   Rigtig auth (worker.js)           Size 5-6      DONE
G26   Lås CORS                          Size 1        DONE
G27   Turso: generations-moenster        N/A           AFKLARET (ingen aendring)
G28   Secrets-scanning (gitleaks)       Size 2        TODO
G29   matching/pricing -> scraper-core  Size 2        TODO (lav prioritet)
----  --------------------------------  ------------  --------
      BUSINESS-SPOR (efter teknisk spor, eller ved omprioritering)
G30   Vinted-fragt: manuelt tjek-flow   TBD           BACKEND+UI DONE (afventer seeding)
G22   Vinted: login-baseret fragt       Size 5-6      DELVIST BLOKERET
G4    Region-filtrering (afhentning)    WSJF 3.5      TODO
G2    Notifikationer (opsummering)      WSJF 4.3      TODO (konens brug)
G3    Beskedudkast + reservation        WSJF 2.0      TODO (konens brug)
```

**Business-features, kort status (detaljer i deres respektive afsnit
nedenfor):**
- **G30 (feature #1):** Vinted-fragt for udenlandske sælgere kan ikke
  hentes automatiseret (DataDome-CAPTCHA på checkout, se G22). Esben
  foreslog i stedet et menneske-i-loopet manuelt tjek-flow -- afventer
  scope-afklaring (ren ad-hoc vs. UI-understøttet genvej).
- **G22:** login-baseret automatiseret Vinted-fragt -- delvist blokeret,
  se dedikeret afsnit for hvad der reelt blev afprøvet og hvorfor.
- **G4 (region-filtrering):** ikke afvist, bare ikke prioriteret endnu.
  Esbens kone skal kunne filtrere fund efter afhentnings-/forsendelses-
  region.
- **G2 (notifikationer):** kvalificeres af Esbens kones faktiske
  brugsmønster -- bevidst ikke bygget før der er reel brug at basere
  designet på (fx: notifikation ved nyt "eksakt match", ikke bare en
  generel opsummering).
- **G3 (beskedudkast/reservation):** samme kvalificerings-gate som G2 --
  automatisk udkast til besked til sælger + evt. reservations-flow, når
  brugsmønsteret retfærdiggør det.

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

**G15 (DONE, 2026-07-10) — Størrelse: eksakt eller næste OP, aldrig mindre.**
Punkt 2. Før gav `matching._size_rank()` "nær" ved BEGGE nabostørrelser
(104 → både 98 og 110). Esben ville: eksakt = bedst, næste størrelse OP
(104→110) = acceptabelt nær-match, MINDRE (104→98) = matcher ALDRIG
(barnet vokser). **Leveret:** `_neighbor_sizes()` returnerer nu KUN
`SIZE_LADDER[idx+1]` (næste op), aldrig `idx-1`. Ekstra: Sellpys interval-
størrelser ("CHILD-CM-98/104") blev tidligere trunkeret til første
(laveste) tal -- det ville have gjort et 98/104-plag "for lille" for et
110-ønske selvom det reelt dækker op til 104. `sources/sellpy.py` bevarer
nu hele intervallet ("98/104"), og ny `matching._item_size_tokens()`
prøver hvert tal i intervallet for sig i `_size_rank()`. **Verificeret:**
16 regressions-cases (eksakt/næste-op/aldrig-ned/G7-tom-størrelse/kant-af-
stige/intervaller) -- alle bestod; `sources/sellpy._parse_cm_size()`
end-to-end-tjekket ("CHILD-CM-80"→"80", "CHILD-CM-98/104"→"98/104",
voksen-skala→""). Size 2, ingen afhængigheder.

**G6 (DONE, 2026-07-10 — punkt 3 slået sammen hertil) — Stand-normalisering.**
Punkt 3 ER en fuld specifikation af det gamle G6. Hver platform angiver
stand FORSKELLIGT (Reshopper "Næsten som ny"/"God, men brugt"/"Defekt,
kan laves"; Sellpy "Nyt/Meget god/God/Acceptabelt"; Vinted "Ny med
prismærker/.../Tilfredsstillende"; DBA fritekst + CONDITION_MAP-fallback).
**Leveret:** 5-trins normaliseret skala i `matching.py`
(`STAND_TIERS = ["ny","naesten_ny","god","brugt","defekt"]`) via
KEYWORD-heuristik (`normalize_stand()`) i stedet for en fast per-kilde
opslagstabel. **RETTELSE (2026-07-11, live verificeret paa ~30 rigtige
DBA-annoncer):** DBAs "Stand"-extra er IKKE fritekst som først antaget
her -- den har et `valueId` (fast facet, ligesom Reshoppers
KNOWN_STAND_LABELS), observeret som valueId 1 "Helt ny - uåbnet/med
prismærke", 2 "Som ny - ingen synlige brugsspor", 3 "Brugt - men i god
stand" (ingen huller i 1-3, formentlig hele sættet for børnetøj).
Keyword-heuristikken beholdes alligevel frem for en per-kilde
opslagstabel, da den allerede klassificerer alle 3 DBA-værdier korrekt
OG robust dækker fremtidige formuleringsændringer på alle 4 platforme
uden kode-ændring. `_stand_ok()` bruger ønskets `stand`-felt som en MINIMUMS-
tærskel (fx "god" accepterer også "næsten_ny"/"ny", ikke kun "god") og er
nu et HARDT matching-kriterie i `match_item()` (samme status som
størrelse/mærke/pris) -- valgt frem for kun visuel nedtoning, fordi Esbens
formulering ("matcher på tværs af platformene") bad om et reelt
matchingkriterie, ikke kun kosmetik. Ukendt/tom stand (på ønske ELLER
annonce) blokerer ALDRIG (benefit of the doubt, samme permissive princip
som G7). `sheets_output.BAD_STAND_LABELS`/`_display_stand` generaliseret
til `_is_bad_stand()` (bruger `normalize_stand()==  "defekt"`) så ALLE
kilders defekt-formuleringer flages, ikke kun Reshoppers ordrette streng.
Ingen skema-ændring (stand_norm beregnes on-the-fly hvert match, ikke
persisteret i DB/Turso). **Verificeret:** 22 `normalize_stand()`-cases +
8 `_stand_ok()`-tærskel-cases + 1 fuld `match_all()`-integrationstest på
tværs af alle 4 kilder (defekt+under-tærskel-fund korrekt udelukket,
ny+næsten_ny-fund korrekt bevaret) -- alle bestod. Size 4-5.

**G16 (DONE, 2026-07-11 — punkt 4+5 slået sammen) — Vinted land +
polsk-nedprioritering.** Planen var at scrape sælgers `profile_url`-HTML
(bot-wall-risiko, DataDome). **Bedre fund under tidlig validering (jf.
spikens advarsel om at validere FØR resten bygges ovenpå):** Vinteds
bruger-API (`GET /api/v2/users/<sælger-id>`) svarer 200 MED JSON HELT
ANONYMT (modsat `/api/v2/items/<id>` der kræver login) og indeholder
`country_code` direkte -- INTET behov for HTML-scraping. Live-verificeret
på 12+ sælgere på tværs af 5 søgetermer (DK/PL/SE observeret).
**Arkitektur-udfordring løst:** `fetch_details()` fik tidligere kun URL'er,
ikke sælger-ID -- den delte to-fase-kontrakt udvidet med et nyt valgfrit
`raw_listings_by_url`-kwarg (accepteret+ignoreret af Reshopper/DBA/Sellpy,
brugt af Vinted). Vinteds candidates blev tidligere markeret "allerede
komplette" (samme genvej som Sellpy) og sprang derfor HELE
detalje-fasen over -- adskilt via nyt eksplicit `SKIP_DETAIL_FETCH`-modul-
flag (`True` for Sellpy, default `False` ellers) i stedet for det gamle
skøre duck-typing-tjek ("har kortet en 'seller_name'-nøgle"). ÉT
land-opslag PR. UNIK SÆLGER pr. koersel (ikke pr. annonce) -- flere
annoncer fra samme sælger genbruger opslaget. **Leveret:** ny
`seller_country`-kolonne i `db.py` (cachet ligesom brand/stand, men
OPDATERES på conflict hvis et senere opslag lykkes hvor et tidligere
fejlede -- modsat brand/seller_name); samme kolonne tilføjet til Tursos
LIVE `matches`-tabel via idempotent `PRAGMA table_info`+`ALTER TABLE`
(CREATE TABLE IF NOT EXISTS rører ikke en allerede-eksisterende
produktionstabel); `matching.py`s `DEPRIORITIZED_SELLER_COUNTRIES = {"PL"}`
sorterer polske sælgere sidst inden for samme match-tier (soft, IKKE
ekskluderet) + synlig `country_warning`-tekst; webapp viser land ved
sælgernavn + samme advarsel; Sheets fik en "Land"-kolonne + samme
advarsels-baggrund som defekt stand. **Verificeret:** fuld
`monitor.run_source()`-kørsel for Vinted (0 "allerede komplette", alle
5 kandidater korrekt gennem det nye land-opslag); Sellpy uændret
(stadig "8 allerede komplette, 0 nye opslag"); syntetisk sorteringstest
(polsk sælger korrekt sidst TROSS laveste pris); DB- og Turso-roundtrip
mod den ægte lokale/produktions-database. **Uheld undervejs (selv-rettet):**
et testskriv ramte ved en fejl LIVE Turso-produktionsdata (overskrev
current_run_id med 1 falsk testmatch) -- opdaget straks, rettet ved at
trigge en rigtig `monitor.py`-kørsel via den kørende
`trigger_watcher.py --source turso`-proces, som gendannede korrekte
data (bekræftet: testrækken væk, 15 rigtige matches tilbage). 52
Vinted-rækker fra FØR G16 nulstillet (`details_fetched=0`) for
naturlig land-backfill ved genopdagelse -- ingen tvungen fuld-backfill
(scope-afgrænset, selvhelende over tid). Size 6-7.

**G17 (DONE, 2026-07-11) — Stand-dropdown (harmoniseret UI).** Esben
spurgte om en dropdown for ønskesedlens stand-felt "med harmoniseret
matching", opfølgning på G6. G6 byggede allerede den harmoniserede
matching-motor (`matching.normalize_stand()`), men ønskesedlens
`#wl-stand`-felt i webappen var stadig et frit tekstfelt (placeholder
"fx som nyt") -- en bruger kunne skrive noget `normalize_stand()` ikke
genkendte, hvilket (per designet permissive fallback) STILLE ingen
stand-krav i stedet for det tilsigtede. **Leveret:** `docs/index.html`s
`#wl-stand` er nu et `<select>` med 5 valg: "Alle stande" (tom, intet
krav), "Ny", "Næsten som ny", "God", "Brugt" -- alle GARANTERET at
normalisere korrekt, da værdierne er identiske med `matching.
STAND_TIER_LABELS`. "Defekt" udeladt af dropdown'en bevidst: som
minimumstærskel er den funktionelt identisk med "Alle stande" (alt
passerer), så den ville blot vaere et forvirrende ekstra valg. Ingen
backend-ændring nødvendig -- samme `stand`-felt/API/DB-kolonne som
før, kun UI'ens input-metode ændret. **Verificeret grundigt:** (1)
`normalize_stand()` kørt paa alle 4 ikke-tomme dropdown-strenge, alle
klassificerer korrekt; (2) fuld 5×5 `_stand_ok()`-minimumstærskel-matrix
(alle kombinationer af ønske × annonce-stand) verificeret korrekt; (3)
live Playwright-test af selve webappen (lokal http-server mod
`docs/index.html`, rigtig adgangskode, rigtig Cloudflare Worker-API):
dropdown'ens 5 optioner bekræftet i DOM'en, en test-ønske tilføjet med
"God" valgt, bekræftet at "Maks 77 kr. · God" vises korrekt i
ønskesedlen, testrækken derefter slettet igen via UI'ens egen
slet-knap og bekræftet fuldstændig væk (ingen rester i Turso). JS-
syntax verificeret med `node --check`. Size 2.

**Prioriterings-begrundelse:** G14+G15 er små, høj-værdi fixes med nul
afhængigheder (gøres først). G6 (stand) er den tunge, veldefinerede
feature. G16 er størst + mest usikker (bot-risiko) -- placeret efter de
sikre gevinster, men foran G4/G2/G3 fordi Esben aktivt har prioriteret
det. G2/G3 forbliver gated på konens faktiske brugsmønster.

**G18 (DONE, 2026-07-11) — Type-matching: fuld taksonomi.** Udløst af
Esbens kones rapport om Vinted-fund der ikke dukkede op. Live-
undersøgelse: søgning "kuling jakke" gav 0/20 gyldige matches, selvom
"Kuling jacka 110" (svensk, præcis rigtig størrelse jf. G15) var blandt
resultaterne -- `TYPE_SYNONYMS` kendte kun synonymer for "leggings" og
"bukser", intet for "jakke". Dansk sammensætning ("vinterjakke") virkede
allerede via substring-match, men fremmedsprogede ord (Vinted blander
svenske/polske/finske sælgere ind i danske søgeresultater, se G16) blev
aldrig genkendt. **Leveret:** hentede Sellpys fulde Algolia-facet
(`metadata.type`, segment=children) -- 200 KONTROLLEREDE danske
typebetegnelser (sælgeren vælger fra dropdown, ikke fritekst), den mest
autoritative "type tree" der findes på tværs af kilderne (Reshopper har
INGEN separat type-facet, kun Alder/Køn/Størrelse/Mærke/Stand, bekræftet
ved DOM-inspektion). Byggede 11 brede synonym-klynger i `matching.py`
(jakke, vest, bukser, leggings, kjole, trøje, t-shirt, skjorte, sæt, sko,
hue) der dækker BÅDE danske ord uden fælles rod (fx "anorak"/"parka" er
ikke "jakke"-sammensætninger) OG live-verificerede fremmedords-STAMMER
(polsk "kurtk"/"spodni"/"sukienk"/"zestaw"/"buty", svensk
"jacka"/"tröj"/"byx"/"kjol", finsk "takki"). `_build_type_synonyms()`
udvider hver klynge til et fladt opslags-dict, så alle 62 ord i en klynge
peger på hele klyngens dækning. Resterende ~150 Sellpy-typer (primært
tilbehør + internationale låneord) er bevidst IKKE klynget -- lavere
værdi, matcher stadig via literal-ord-fallback som før. **Verificeret:**
16 syntetiske regressionscases (inkl. at "vest" bevidst IKKE matcher
"jakke"-ønsker, og at leggings/bukser forbliver adskilte); genkørsel af
den ORIGINALE "kuling jakke"-søgning gik fra 0/20 til 5/20 bestået
precheck (resten korrekt udelukket af G15's størrelsesregel, ikke type);
fuld live-test med Esbens 3 aktuelle ønsker fandt nu reelle
jakke-kandidater der før var usynlige. Kendt resterende hul (accepteret,
ikke forfulgt videre): produkter beskrevet kun ved materiale/stil uden et
genkendt type-ord (fx "Vindfleece" uden "jakke"/"jacka"-stamme) fanges
stadig ikke -- diminishing returns ift. risiko for falske positiver ved
at udvide yderligere. Size 6.

**G19 (DONE, 2026-07-11) — Automatisk periodisk kørsel.** Sideeffekt-fund
fra G18-undersøgelsen: `launchctl`/`crontab` viste INGEN planlagt opgave
for Personal Shopper overhovedet -- README dokumenterede eksplicit at
det 2x-dagligt scheduled-task ALDRIG var installeret ("IKKE installeret
automatisk"). Systemet havde derfor ALTID udelukkende kørt når nogen
manuelt trykkede "Kør nu" -- konkret observeret: sidste kørsel kl. 00:08,
tjekket igen kl. 08:45 -- 8,5 timers datastilstand uden nogen har
trykket "Kør nu". Forklarer sandsynligvis (helt eller delvist) hvorfor
konens Vinted-fund ikke var synlige. **Leveret:** Esben valgte 5×
dagligt (06/10/14/18/22). `~/Library/LaunchAgents/com.local.personal-
shopper.plist` oprettet (StartCalendarInterval med 5 tidspunkter, minut
0), valideret med `plutil -lint` og indlæst med `launchctl load` --
bekræftet registreret via `launchctl list`. Kører `monitor.py` direkte
(ikke `trigger_watcher.py` -- den er til manuelle "Kør nu"-tryk, denne
er en uafhængig periodisk kørsel), skriver til BÅDE Sheets og Turso jf.
`config.yaml`s `output.targets`. README.md's launchd-sektion opdateret
til at afspejle det faktiske 5×-skema i stedet for det tidligere
2×-eksempel. Kendt, accepteret risiko (uændret fra G5): to overlappende
`monitor.py`-kørsler (en periodisk + en manuel "Kør nu" der rammer
samtidig) er ikke et fuldt distribueret lock, men generations-swappet
håndterer det pænere end en simpel overskrivning ville.

**G20 (DONE, 2026-07-11) — Type-filter + tydelig pris/fragt/total.**
Esben bad om (a) en filtermekanisme i webappen så man fx kan se jakker
samlet, og (b) tydelig vare-/fragt-/totalpris så filteret kan bruges til
at finde det billigste fund. **Leveret (kun `docs/index.html`, ingen
backend-ændring):** ny "Type"-dropdown filtrerer på `wishlist_type`
(ønskesedlens EGET type-felt, ikke annoncens rå titeltekst) -- så et
"jakke"-filter grupperer korrekt uanset om fundet selv hedder "jakke"/
"jacka"/"kurtka" (genbruger G18s fremmedsprogsdækning uden ekstra
arbejde). Ny "Sortér"-dropdown: Bedste match (uændret backend-
rækkefølge) / Billigst inkl. fragt / Billigst kun vare. Hvert match-kort
viser nu en tydelig prislinje: "Vare: X kr. · Fragt: Y kr. · Total: Z
kr." -- eller "Fragt: ukendt" når kilden ikke har fragtdata (Sellpy/
Vinted uden login, se deres moduler); total beregnes ALDRIG ved at
antage 0 kr. fragt, kun når begge dele reelt kendes. Alt filter/sortér
sker klient-side på det allerede hentede datasæt (ingen ekstra API-kald).
**Verificeret:** live mod produktions-API -- type-dropdown korrekt
befolket (bukser/jakke/leggings), "jakke"-filter viste 8/16 kort inkl.
"Kuling jacka 110" (den svenske titel), total-sortering korrekt stigende
for kendte totaler; ingen mobil-overflow ved 320px/375px. Size 3.

**G21 (DONE, 2026-07-11) — Sellpy: reel fragt (login-fri).** Esben bad
om en dyb undersøgelse af om udenlandske Vinted-fund (Polen/Sverige) får
korrekt beregnet fragt til Danmark. **Fund #1 (Vinted):** BEKRÆFTET at
kræve login -- `/api/v2/shipments/rates` svarer direkte "Medlemslogin
påkrævet" fra selve API'et (ikke bare manglende felter). **Fund #2
(kritisk bug, RETTET):** `bundling.py`s `default_shipping_dkk=39.0`-
fallback var IKKE land-bevidst -- en rigtig finsk sælger ("annrist", 2
ægte Reima-jakker) fik den danske indenrigs-antagelse (39 kr) i stedet
for en realistisk international fragtpris, og bundlen blev selvsikkert
vist som "betaler sig: True". **Fund #3 (overraskelse, RETTET):** Sellpy
var IKKE reelt "ukendt fragt" som antaget -- prisen ("Fragt fra 39 DKK")
er offentligt synlig på annoncesiden, blot client-side React-renderet
(usynlig for et almindeligt HTTP-kald). Fandt ved at intercepte
netværkskald at Sellpys frontend selv henter prisen fra et HELT
OFFENTLIGT, LOGIN-FRIT GraphQL-endpoint
(`sellpy-parse-prod.herokuapp.com/graphql?_=getFreightAlternatives`) --
kun en offentlig klient-app-ID + en vilkårlig UUID som "installations-ID"
kræves, INGEN cookies/session. **Leveret:** `sources/sellpy.py`s
`SKIP_DETAIL_FETCH` sat til False (var True), ny `fetch_details()` slår
nu billigste fragtmulighed op pr. kandidat via dette endpoint (samme
to-fase-arkitektur som Vinteds land-opslag, G16). **Verificeret:** live
`monitor.run_source()`-kørsel for Sellpy -- 6/6 kandidater korrekt
beriget med `shipping_price=39.0`. **Samme cache-faelde som G16 ramte
også her** (glemt i første omgang): eksisterende Sellpy-rækker i lokal
`seen.db` havde allerede `details_fetched=1` fra FØR G21 (dengang
SKIP_DETAIL_FETCH=True selv satte det, "allerede komplet fra kortet"),
så de sprang det nye fragt-opslag over via cachen og forblev NULL i den
første produktionskørsel efter denne fix. Samme éngangsløsning som G16:
nulstillede `details_fetched=0` for alle 87 Sellpy-rækker, ny kørsel
bekræftede 7/7 friske Sellpy-matches nu korrekt fik `shipping_price=39.0`.
**Fund #2-bugget rettet med det
samme** (kræver ikke Vinted-login, kun den allerede kendte
`seller_country`, se G16): `bundling.py`s `build_bundles()` bruger nu
IKKE `default_shipping_dkk` for en kendt udenlandsk sælger uden reel
fragtdata -- `shipping_dkk=None`, `bundle_worth_it=False` (konservativt,
ikke et gæt), ny `shipping_unknown_foreign`-flag. Sorterings-crash
(`-None`) i samme funktion fanget og rettet undervejs (usikre bundles
sorteres bagerst, ikke først). `sheets_output.py` fik `_or_blank()` +
`_bundle_worth_it_text()` (viser "USIKKERT (udenlandsk sælger)" i stedet
for et misvisende "NEJ"); `docs/index.html` fik en ny grå
"Fragt ukendt"-tag (hverken "Betaler sig" eller "Kun 1 item" er sandt
for en 2+-vares bundle med ukendt fragt). **Verificeret:** genkørt den
finske "annrist"-bundle -- fragt/betaler-sig gik fra det forkerte
39kr/True til korrekt None/False; regressionstestet at KENDT fragt
(dansk sælger) og UKENDT LAND (Reshopper, intet `seller_country`-felt
overhovedet) begge forbliver uændrede; blandet sortering uden crash;
isoleret Playwright-test af `renderBundles()` med syntetiske data
bekræftede begge visningstilstande. **Vinted-delen** (rigtige tal
i stedet for "ukendt") afventer stadig G22's login. Size 3.

**G22 (DELVIST BLOKERET, 2026-07-11/12) — Vinted: login-baseret fragt.**
Esben oprettede en dedikeret Vinted-konto og eksporterede en session
(`.vinted_storage_state.json`, gitignored, samme mønster som DBA).
Bekræftet: sessionen ER reelt logget ind. MEN selve fragtberegningen
sker IKKE ved almindeligt sidebesøg -- kun ved reel købsintention. At
klikke "Køb nu" (Playwright, automatiseret) udløste `POST /api/v2/
purchases/checkout/build` -> **403 + DataDome CAPTCHA-udfordring**,
SELV MED gyldig login. Samme principielle grænse som DBAs login-
CAPTCHA: automatisering stopper her, ubetinget.
En Opus-research-runde (selvstændig agent) undersøgte grundigt om en
lovlig, ikke-CAPTCHA-vej findes: Vinteds egen prisliste har INGEN
fragttabel; hele det undersøgte open source Vinted-scraper-økosystem
(4 populære biblioteker) har samme begrænsning; `routes.vintedgo.com`
(Vinteds login-frie fragtlabel-værktøj) blev testet direkte og
dækker slet ikke Polen/Sverige/Finland/Danmark (kun FR/IT/ES/BE/NL/PT/
GB, bekræftet fra sidens egne data). **Konklusion: intet automatiseret,
lovligt alternativ findes.** Et forsvarligt ESTIMAT blev dog fundet:
Vinteds egen integrerede grænseoverskridende fragt koster typisk
€6-10 (~45-75 kr.) for en lille/mellem pakke -- IKKE detail-
fragtpriser (PostNord-listepriser er 134-200 kr., ville overvurdere
massivt). Automatiseret opslag droppes; se G30 for den
menneske-i-loopet-løsning Esben foreslog i stedet. Size 5-6 (brugt).

**G23 (DONE, 2026-07-12) — Sti-flytning (`~/CC/`-konvention) +
trigger_watcher-launchd-konsolidering.** Projektet flyttet fra
`/Users/server/# Claude tmux/PLAGG/personal-shopper` til
`/Users/server/CC/PLAGG/personal-shopper` (Esben-drevet, `#`-tegnet i
den gamle sti gav bekræftede Vitest/shell-problemer på tværs af
projekter). **Fund + rettet:** (1) `config.yaml`s `google_sheets.
credentials_file` pegede stadig på den GAMLE, nu-slettede absolutte
sti til service account-nøglen i søsterprojektet `ejendompython` --
bekræftet at dette FAKTISK havde ramt mindst 2 planlagte kørsler
(18:01 og 22:01) som stille faldt tilbage til lokale CSV-filer i
stedet for at skrive til det rigtige Sheet (Turso/webappen var
upåvirket, uafhængige try/except-blokke). Rettet til den nye
`~/CC/CCBOILERPLATE/OLD REPOS/ejendompython/google_credentials.json`
-- verificeret direkte (`get_sheets_client()` + `open_by_key()`) OG
via en frisk kørsel der korrekt skrev til det ægte Sheet. (2) To
`trigger_watcher.py`-processer kørte som ikke-superviserede manuelle
terminal-processer (én pr. sheet/turso-kilde) -- begge fulgte cwd
korrekt med ved flytningen (macOS), men havde begge fejlet i deres
logs undervejs (stale sti-referencer / forbigående DNS-fejl). Begge
konverteret til RIGTIGE launchd-jobs (`com.local.personal-shopper-
trigger` + `-turso`, KeepAlive+RunAtLoad, adskilte log-stier) --
overlever nu crashes/genstart, ligesom `com.local.personal-shopper`
(G19) allerede gjorde. Begge kilder BEVARES parallelt (Sheets-sporet
røres aldrig uden eksplicit instruks). Verificeret: begge nye
launchd-jobs kører, ingen fejl i logs efter genstart.

**G24 (DONE, 2026-07-13) — Healthcheck-ping.**
`scraper-core` tilføjet som git-dependency i `requirements.txt`
(`pip install git+https://github.com/fddigi/scraper-boilerplate.git@main
#subdirectory=packages/scraper-core`, verificeret installerbart med
PLAGGs egen Python 3.11-venv). Ny `monitor.load_healthcheck_url()`
læser `HEALTHCHECK_URL` fra `secrets.env` (samme manuelle 'KEY=value'-
parsing + env-override-mønster som `turso_io.load_turso_config()`) --
tom streng hvis ikke sat, hvilket gør `ping_success()`/`ping_fail()`
100% no-op-safe. Ping tilføjet additivt ved ALLE 3 af `monitor.py`s
terminal-grene: `ping_fail()` ved "ingen kilder konfigureret" og "alle
kilder fejlede", `ping_success()` ved den normale succesfulde
afslutning (efter `write_final_status()`, samme steder). Skippes
korrekt for `--dry-run` (samme princip som selve output-skrivningen).
**Verificeret grundigt:** (1) no-op bekræftet for tom/None URL, ingen
undtagelse; (2) en lokal dummy-HTTP-server bekræftede `ping_success()`
rammer base-URL'en og `ping_fail()` rammer `/fail`-suffikset korrekt;
(3) en ægte `--dry-run`-kørsel gennemførte uden fejl (ingen ping, som
tilsigtet); (4) en ÆGTE (ikke dry-run) kørsel af `monitor.py` mod en
lokal dummy-healthcheck-server bekræftede PRÆCIS ét success-ping
modtaget, SAMTIDIG med at både Sheets og Turso blev skrevet korrekt --
ingen regression i eksisterende output. Esben oprettede sit
healthchecks.io-check og tilføjede URL'en til `secrets.env` (fandt
undervejs: nøglen hed ved en fejl `HEALTHCHECK_IO_URL`, ikke
`HEALTHCHECK_URL` som koden læser -- rettet). **Verificeret LIVE mod
den ægte produktionskørsel** (kl. 07:12-07:14): ingen fejl/advarsler i
`monitor.log` omkring kørslen, Sheets+Turso begge korrekt opdateret
(21 matches, 1 bundle) -- healthcheck-pinget er bevidst tavst ved
succes, så fraværet af fejl-linjer bekræfter et vellykket ping. Size 1.

**G25 (DONE, 2026-07-13) — Rigtig auth i `worker.js`.** Erstatter den
tidligere delte `X-API-Key` (synlig i DevTools, ingen session, ingen
rate-limiting) med PBKDF2-hashet kodeord + HMAC-signerede sessions,
porteret fra `scraper-boilerplate`s `auth.ts`/`middleware.ts`/
`rateLimit.ts` -- EFTER skabelon-teamet selv delte den framework-
uafhængige split (`authenticateRequest()`-kerne + Hono-adapter, commit
`0d6fb33`), som ublokerede den tidligere afventende omskrivning.

**KRITISK, IKKE selv fundet her -- porteret læring:** to reelle
produktions-fund fra skabelonens egen historik BLEV RETTET FØR PLAGG
kunne ramme dem: (1) sessionen sendes som `Authorization: Bearer
<token>`-HEADER, ALDRIG en cookie -- et cookie-forsøg i skabelonen
fejlede reelt i Safari, fordi GitHub Pages og Workeren ligger på to
FORSKELLIGE top-level-domæner (third-party-cookie, blokeret af Safaris
ITP uanset `SameSite`) -- login så ud til at lykkes ét øjeblik og
hoppede så tilbage til login-siden. (2) `PBKDF2_ITERATIONS = 100_000`,
IKKE et højere tal -- Cloudflare Workers' ÆGTE produktions-
`crypto.subtle` håndhæver et HÅRDT loft på 100.000 iterationer, som
hverken unit-tests eller `wrangler dev` fanger (kun den RIGTIGT
deployede Worker) -- et for højt tal ville have gjort ALT login stille
fejle med en generisk "forkert kodeord"-besked.

**Leveret:** `hashPassword()`/`verifyPassword()`/`createSessionToken()`/
`verifySessionToken()`/`authenticateRequest()`/
`checkAndIncrementLoginAttempts()` porteret 1:1 til plain `worker.js`
(ingen Hono-afhængighed). Nyt `POST /api/login` (kun `{password}` --
Esben valgte ét delt husstands-kodeord, ikke per-bruger-konti, samme
"klematis" beholdt men nu rigtigt hashet), `POST /api/logout`
(symmetri, stateless). Nyt `RATE_LIMIT_KV`-namespace oprettet
(`wrangler kv namespace create`) + bundet i `wrangler.toml`, 5 forsøg/
15 min pr. IP. Nye Cloudflare secrets `PASSWORD_HASH`/
`SESSION_HMAC_SECRET` sat non-interaktivt (den gamle `API_KEY`-secret
efterladt urørt, men ikke længere brugt -- kan fjernes når G25 har
kørt stabilt i produktion). CORS' `Allow-Headers` byttet fra
`X-API-Key` til `Authorization`. Frontend: `LS_KEY` omdøbt til
`plagg_session_token` (gemmer nu et signeret token, ALDRIG det rå
kodeord), `apiFetch()` sender `Authorization: Bearer`-header og
auto-detekterer et 401 (udløbet/ugyldigt token) -> rydder det gemte
token og genviser login-prompten automatisk. `showPasswordPrompt()`
kalder nu `POST /api/login` i stedet for at teste mod `/api/status`.

**Verificeret grundigt LIVE mod den ægte deployede Worker** (ikke kun
lokal Node-simulation, jf. iterations-loft-fundet ovenfor): korrekt
login (200+token), forkert kodeord (401), manglende/ugyldigt token på
beskyttede endpoints (401), rate-limiting (5. forsøg 429, bekræftet
ved selv at ramme det og finde+slette min egen KV-testnøgle for at
fortsætte), logout (200 med token, 401 uden). FULD Playwright-browser-
test: forkert kodeord viser fejl, korrekt kodeord logger ind og loader
rigtige data, et bevidst korrumperet gemt token trigger automatisk en
ny login-prompt uden manuel sideopdatering, ingen mobil-overflow ved
320px/375px. Size 5-6.

**G26 (DONE, 2026-07-12) — Lås CORS.** Esben valgte: tillad BÅDE
Pages-domænet og localhost. `worker.js`s `CORS_ORIGIN = "*"` erstattet
med en eksplicit allow-liste (`ALLOWED_ORIGINS` + `ALLOWED_ORIGIN_
PREFIXES` for `localhost:<port>`/`127.0.0.1:<port>`, portnummer
varierer fra test til test). `Access-Control-Allow-Origin` ekkoer nu
KUN den matchende Origin tilbage (aldrig `*`) + en `Vary: Origin`-
header (svaret afhænger af Origin, må ikke caches på tværs). Klargør
samtidig G25's kommende session-cookies (`Access-Control-Allow-
Credentials` er uforenelig med `*`-origin). **Verificeret live** mod
den deployede Worker: Pages-domæne + localhost får korrekt deres
Origin ekko'et tilbage; et simuleret ondsindet kopi-domæne
(`evil-copycat.example.com`) får INGEN CORS-header overhovedet
(browseren blokerer klientsidigt). Size 1.

**G27 (AFKLARET, 2026-07-13 — ingen ændring i PLAGG lige nu) — Turso-
generations-mønster.** Esben bad om at undersøge hele delta-sync-
spørgsmålet grundigt (ikke kun et transport-swap). Spurgt direkte til
`scraper-boilerplate`-teamet: byg et separat, førsteklasses
`scraper_core.generations`-modul til PLAGGs mønster, eller lad være?

**Svar:** Bygget (commit `9496d97`) -- MED en vigtig selvstændig
rettelse undervejs. Teamets FØRSTE udkast af `generations.py` havde to
reelle korrekthedsfejl, fundet ved at bruge PLAGGs `turso_io.py` som
reference: (1) `run_id` var wall-clock-baseret i stedet for en atomisk
server-side tæller (kan kollidere/gå tilbage ved urskævhed); (2)
`cleanup_superseded()` brugte netop det brede "slet-alt-der-ikke-er-
current"-mønster som PLAGGs G5-FIX-kommentar advarer imod -- PRÆCIS
den race condition PLAGG selv fandt og rettede tidligere denne
sæson. Rettet til at matche `write_matches_and_bundles()`s mønster
1:1 (`allocate_run()` -> atomisk `(run_id, superseded_run_id)`,
`publish_generation()` returnerer om man vandt raceren,
`cleanup_superseded()` tager et EKSPLICIT `superseded_run_id` og
kaldes kun af vinderen), inkl. en regressionstest for netop dette
scenarie.

**Konklusion/beslutning:** ingen migrering af `turso_io.py` lige nu.
PLAGGs egen implementering er BEKRÆFTET korrekt (en uafhængig
genopbygning, brugt som reference, fandt ingen fejl i selve mønsteret
-- kun i skabelonens FØRSTE forsøg på at genskabe det) og allerede i
produktion. En migrering ville udskifte den LIVE data-skrive-sti for
et værktøj familien aktivt bruger dagligt, uden nogen aktiv bug at
rette -- gevinsten (mindre selv-vedligeholdt kode) er reel, men ikke
uopsættelig. API'et er tilgængeligt hvis/når det bliver relevant:
`ensure_control_table()`+`ensure_control_row()` ved opstart, derefter
pr. kørsel `allocate_run()` -> `insert_generation_rows()` (én gang pr.
tabel) -> `publish_generation()` (én gang) -> `cleanup_superseded()`
(én gang pr. tabel, kun ved vundet race). Ingen kode-ændring i PLAGG
som følge af denne undersøgelse -- kun ekstern validering af et
allerede korrekt, allerede leveret mønster (G5-FIX). Size: N/A (ingen
implementering).

**G28 (DONE, 2026-07-13) — Secrets-scanning.** `gitleaks` (v8.30.1) +
`pre-commit` (v4.6.0) installeret via brew. Ny `.gitleaks.toml`
(tilpasset PLAGG -- ingen `.env.example` findes, kun `wrangler.toml`-
FILNAVNET er path-allowlistet). **Engangs-scan af HELE git-historikken
(32 commits, ikke kun fremadrettet, per Esbens instruks):** fandt
PRÆCIS ét flag -- Sellpys Algolia-SØGE-nøgle i `sources/sellpy.py`
(bekræftet i modulets egen docstring: offentlig, client-side, search-
only, ikke en admin-nøgle -- samme princip som Reshopper/DBA's
hardcodede URL'er). Allowlistet med en PRÆCIS regex-streng-match (ikke
en bred fil-udelukkelse), så et FREMTIDIGT reelt fund i samme fil
stadig ville blive fanget -- verificeret eksplicit ved midlertidigt at
fjerne allowlist-reglen og bekræfte scanneren korrekt genfandt nøglen.
**INGEN andre hemmeligheder fundet** -- det tidligere `.env.save`-fund
(slettet FØR commit, aldrig faktisk verificeret fraværende fra
historikken med et rigtigt værktøj) er nu bekræftet: findes IKKE i
historikken. `.pre-commit-config.yaml` tilføjet (kun gitleaks-hooken,
Esben bad specifikt om secrets-scanning, ikke linting) og
`pre-commit install` kørt -- **verificeret fungerende ende-til-ende**:
et testcommit med en fake Stripe-nøgle blev korrekt BLOKERET (exit
code 1, ingen commit lavet), et harmløst testcommit passerede
uhindret. Begge testcommits fjernet igen bagefter (ingen af dem
pushet). Size 2.

**G29 (DONE, 2026-07-13) — matching/pricing -> scraper-core.**
`matching.py`s `_build_type_synonyms()` erstattet med `scraper_core.
matching.build_synonym_lookup()`, `_type_matches()`s opslag erstattet
med `expand_synonyms()` -- PLAGGs egne `_TYPE_CLUSTERS` (domaene-
indhold) uaendret, kun opslags-MEKANIKKEN er delt nu. Alle 4 kilders
manuelle `.replace(".","").replace(",",".")`-prisparsing erstattet med
`scraper_core.pricing.parse_price()`: Sellpy (`unit="minor"`, den
konkrete oere-bug-klasse dette blev bygget til), Vinted (`unit="major",
decimal_style="dot"`), Reshopper/DBA (`unit="major", decimal_style=
"comma"`, 3 kaldssteder inkl. DBAs delte `_parse_kr_amount()`-
fragttekst-parser). **KRITISK FUND undervejs (fanget FØR produktion):**
`decimal_style="auto"` (modulets default) fejlfortolkede en Reshopper/
DBA-pris UDEN komma overhovedet (fx "1.234 kr." for et helt tusind,
ingen øre) som punktum-decimal -- gav 1.234 i stedet for korrekt 1234.0,
en ~1000x for lav pris. Årsag: Reshopper/DBA er ALTID dansk-formaterede,
aldrig tvetydige med engelsk konvention -- "auto" er designet til
tvetydige/blandede kilder, hvilket disse ikke er. Rettet ved at TVINGE
`decimal_style="comma"` eksplicit for begge kilder (ikke stole på
auto-detektion) -- dette var IKKE dokumenteret risiko fra evalueringen,
men fundet ved grundig regressionstest, se rapporterede fund til
`scraper-boilerplate`-agenten. **Verificeret:** alle 18 tidligere G18-
type-matching-regressionscases uændret korrekte; 7 pris-parsing-
regressionscases inkl. det kritiske "helt tusind uden komma"-scenarie;
LIVE mod alle 4 rigtige kilder -- Reshopper ramte reelle 4-cifrede
priser ("1900.0", "1300.0" for klapvogne), DBA ligeså ("7800.0",
"3000.0", "2500.0"), begge korrekt parset (ville have været ~1000x for
lave med "auto"); Sellpy/Vinted uændret korrekte. Fuld `monitor.py
--dry-run` (alle 4 kilder) kørt igennem uden fejl, 21 matches, 1
bundle. `watchdog.py`s `run_with_timeout()` (per-kilde timeout,
supplement til `hang_guard.py`s proces-niveau watchdog) IKKE taget i
brug -- lavere prioritet, ingen akut anledning. Size 2.

**G30 (BACKEND+UI DONE, 2026-07-13 — afventer seeding, business #1) —
Vinted-fragt: manuelt tjek-flow.** Erstatning for det automatisk-
blokerede spor i G22. Esben: et menneske gennemfører selv et par
checkout-klik i egen browser (løser en evt. CAPTCHA som menneske,
samme princip som DBA-login) og rapporterer de observerede rigtige
fragttal tilbage -- IKKE automatisering, et bevidst manuelt datapunkt-
indsamlings-flow, med backend der husker fragt PR. TERRITORIUM og
tager et LØBENDE GENNEMSNIT (overlever at de underliggende annoncer
forsvinder).

**Data-lag:** ny Turso-tabel `shipping_observations` (id, source,
country, shipping_price, observed_at) -- ÉT raekke PR. OBSERVATION
(aldrig en overskrivning), gennemsnittet beregnes ved LAESNING
(`turso_io.get_shipping_estimates()`). `MIN_SHIPPING_OBSERVATIONS = 10`
(duplikeret som konstant i baade `turso_io.py` og `bundling.py`, bevidst
IKKE en import for at `bundling.py` forbliver Turso-fri) -- under
graensen vises fortsat "ukendt", ikke et upaalideligt estimat.

**Backend:** `bundling.apply_shipping_estimates()` (nyt) beriger
matches IN-PLACE med adskilte `shipping_price_estimate`/
`shipping_price_estimate_count`-felter -- `shipping_price` (det
BEKRAEFTEDE felt) roeres ALDRIG, samme "gaet aldrig stille"-princip som
G6/G16/G20/G21. `build_bundles()` fik et nyt `country_shipping_
estimates`-argument (default `None` = PRAECIS G21-fixets adfaerd,
ingen regression) -- naar et lands gennemsnit er over graensen bruges
det som `shipping_dkk` med `shipping_is_country_estimate=True`
(adskilt fra den gamle danske `shipping_is_assumed`-antagelse), og
bundle-oekonomien (total/effektiv pris/besparelse/"betaler sig")
beregnes nu KORREKT med det data-baserede tal i stedet for at forblive
"ukendt". `monitor.py` henter `country_shipping_estimates` ÉN gang i
hovedtraaden (samme moenster som `cached_details`, G10) og giver det
read-only videre til hver kildes `run_source()`-kald.

**API:** to nye `worker.js`-endpoints -- `GET /api/shipping-estimates`
(samme `{land: {avg, count}}`-form som Python-siden) og
`POST /api/shipping-observation` (server-side valideret: 2-bogstavs
landekode, positiv pris maks. 2000 kr., samme princip som den
eksisterende `POST /api/wishlist`-validering).

**UI (webapp):** individuelle Vinted-matches for kendte udenlandske
lande viser nu enten "Fragt: ~65 kr. (estimat, 12 obs.)" (som et link
til den AEGTE annonce, saa man selv kan tjekke prisen ved checkout)
eller "Fragt: ukendt" -- BEGGE med en ✏️-knap der aabner en dialog
("Hvad var den reelle fragtpris?"), poster til det nye endpoint, og
genindlaeser data. Bundles viser samme estimat + observationstal i
deres eksisterende fragt-linje. Blyanten sidder bevidst KUN paa
individuelle matches, ikke bundles (bundles arver automatisk samme
landegennemsnit via backend'en -- ingen dobbelt-rapporterings-UX
noedvendig). **Sheets** viser estimatet som ren tekst
("~65 kr. (estimat, 12 obs.)") via nye `_match_shipping_display()`/
`_bundle_shipping_note()`-helpers -- UDEN blyant/dialog (ren
interaktiv webapp-funktion, Sheets forbliver read-mostly).

**Verificeret grundigt:** ny skema+funktioner testet direkte mod ægte
Turso (skriv, laes, idempotent skema-udvidelse); `bundling.py`s 4
scenarier (uden estimater = uaendret G21-adfaerd; under graensen =
fortsat "ukendt"; over graensen = korrekt estimat+oekonomi; dansk
kendt-fragt-saelger upaavirket); `apply_shipping_estimates()` LIVE mod
rigtige Vinted-fund (5 PL + 1 SE-fund korrekt beriget); Worker-
endpoints LIVE deployet og testet (gyldig observation, ugyldig
landekode -> 400, negativ pris -> 400, manglende API-key -> 401);
`sheets_output.py`s nye helpers unit-testet (7 cases); FULD Playwright-
UI-test mod produktions-API -- aabn dialog, valideringsfejl ved tom
input, gem en observation, bekraeft den REELT naaede Turso, dialog
lukker korrekt; ingen mobil-overflow ved 320px/375px (baade med og
uden aaben dialog).

**Afventer:** seeding af min. 10 observationer for Polen/Sverige/
Finland (de hyppigst ramte lande) foer estimater rent faktisk vises i
praksis -- systemet virker korrekt med 0 data (viser "ukendt" som i
dag), saa dette blokerer IKKE selve funktionens korrekthed. Kan ikke
gøres af Claude i denne session (ingen synlig/interaktiv browser paa
denne homelab-server, se separat Claude-i-Chrome-prompt til Esben).

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

## Historisk udestående-liste (2026-07-09) — ALLE punkter siden afklaret

> Denne sektion er forældet og bevaret kun som historik. Alle punkter
> herunder er enten leveret eller er blevet en del af den aktive backlog
> øverst i filen ("Aktiv backlog (næste øverst)") -- se den i stedet for
> aktuel status.
>
> - G5 (webapp som dagligt dashboard): LEVERET, live siden 2026-07-10.
> - G2/G3 (notifikationer/beskedudkast): stadig i business-sporet ovenfor,
>   fortsat gated på Esbens kones faktiske brug.
> - G4 (region-filtrering): stadig i business-sporet ovenfor.
> - launchd (2x-dagligt + trigger_watcher): LEVERET/opdateret, se G19
>   (automatisk periodisk kørsel) og G23 (sti-flytning + launchd-
>   konsolidering af begge trigger_watcher-instanser).
> - DBA-session: fortsat samme bevidste ikke-automatiserede design (G1),
>   ingen ændring.
> - Git-repo: leveret, `FirstDawnDigital/Plagg` er offentligt og aktivt.

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
