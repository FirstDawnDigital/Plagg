#!/usr/bin/env python3
"""Personal Shopper -- branch "Brugt børnetøj" (Reshopper + DBA).

Overvaager Reshopper.com OG DBA.dk for annoncer der matcher en oenskeseddel,
beregner bundling pr. saelger PR. KILDE (fragt-oekonomi -- se bundling.py's
_seller_key, en Reshopper- og en DBA-saelger grupperes ALDRIG sammen) og
skriver resultatet til et Google Sheet-dashboard. Se personal-shopper-
brief.md for den fulde opgavebeskrivelse, BACKLOG.md for F1-spikens fund
(styrer Reshopper-scraping-tilgangen) og G1-fund (DBA: login-session i
.dba_storage_state.json, se sources/dba.py).

Kør: python monitor.py [--dry-run] [--source reshopper|dba]
"""
import argparse
import concurrent.futures
import datetime
import logging
import logging.handlers
import os
import sys

import yaml

import bundling
import db
import hang_guard
import matching
import sheets_output
import turso_io
import wishlist as wishlist_module
from sources import dba, reshopper, sellpy, vinted

# Haard global graense for HELE monitor.py-processens koerselstid, UANSET
# hvordan den kaldes (direkte `python3 monitor.py`, via trigger_watcher.py,
# eller ad-hoc af en agent) -- se hang_guard.py's docstring for hvorfor. Dette
# er sikkerhedsnettet der ville have fanget natten-mellem-2026-07-09/10s
# 8+-timers-haengning (som skete ved en DIREKTE koersel, altsaa UDEN
# trigger_watcher.py's eget RUN_TIMEOUT_S=30*60 subprocess-timeout som
# sikkerhedsnet). Sat lavere end trigger_watcher.py's 30 min, saa DENNE
# watchdog naar at gribe ind foerst og logge en tydelig "WATCHDOG"-besked
# FOER trigger_watcher.py's subprocess.run(timeout=...) i stedet ville have
# afbrudt processen udefra uden nogen forklarende besked i monitor.log.
# Overskriv med config.yaml's 'watchdog_timeout_s' hvis 22 min. viser sig for
# stramt/loest i praksis (se J6-fundet i trigger_watcher.py: reelle koersler
# har spaendt 2,5-14 min., saa 22 min. giver rigelig margen uden at aabne for
# timevis-lange haengninger).
DEFAULT_WATCHDOG_TIMEOUT_S = 22 * 60

SOURCE_MODULES = {
    "reshopper": reshopper,
    "dba": dba,
    "sellpy": sellpy,
    "vinted": vinted,
}

# Visningsnavne til kilde-fremdriftsindikatoren (se main()) -- rene kosmetik,
# paavirker intet i selve scraping-logikken.
SOURCE_DISPLAY_NAMES = {
    "reshopper": "Reshopper",
    "dba": "DBA",
    "sellpy": "Sellpy",
    "vinted": "Vinted",
}

logger = logging.getLogger("personal_shopper")


def setup_logging(log_path: str) -> None:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_search_terms(wishlist: list[dict]) -> list[str]:
    """Bygger soegetermer ud fra oenskesedlens type+mærke-kombinationer
    (brief §7/§9: "overvaager ... for de typer/mærker der er paa oenskesedlen").
    Dedupliker saa vi ikke soeger samme term to gange for to ens raekker."""
    terms = []
    seen = set()
    for item in wishlist:
        term = f"{item.get('maerke', '')} {item.get('type', '')}".strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return terms


def run_source(
    source_name: str,
    source_module,
    config: dict,
    wishlist: list[dict],
    dry_run: bool,
    cached_details: dict | None = None,
) -> tuple[list[dict], list[dict], bool, list[dict]]:
    """Koerer én kilde (reshopper/dba/sellpy/vinted -- alle foelger samme
    to-fase fetch()/fetch_details()-kontrakt, se sources/*.py) i eget
    try/except -- en fejl her maa aldrig vaelte resten af scriptet (samme
    princip som PA SPEAKERS-arkivets monitor.py:run_source). Returnerer
    (matches, bundles, ok, detail_cached_candidates) -- tomme lister og
    ok=False hvis kilden fejler helt (undtagelse undervejs), ok=True hvis
    kilden koerte igennem uden undtagelse (ogsaa hvis den reelt fandt 0
    matches -- det er en gyldig markedstilstand, ikke en fejl). G5-FIX
    (fund #4): denne ok-status bruges af main() til at skelne "koerte, fandt
    0" fra "fejlede helt", saa vi ikke fejlagtigt overskriver Turso/Sheets med
    tomme resultater naar ALLE kilder reelt bare fejlede (fx forbigaaende
    netvaerksfejl).

    G10 (hastighedsoptimering): 'cached_details' er db.cached_details_map()'s
    resultat (id -> {brand, size, stand, seller_name, seller_id,
    shipping_price}), laest ÉN gang i hovedtraaden FOER kilderne startes (se
    main()) og givet videre som et READ-ONLY dict til hver kildes
    worker-traad -- samtidig laesning af samme dict fra flere traade er
    sikkert i Python, kun skrivning kraever hovedtraad-disciplin (allerede
    etableret). For enhver kandidat-URL hvis id (db.make_id) findes i
    cached_details springer vi det dyre fetch_details()-kald HELT over og
    genbruger brand/size/stand/seller_name/seller_id/shipping_price derfra --
    prisen tages ALTID fra det friske kort, aldrig fra cachen (den kan aendre
    sig). 'detail_cached_candidates' i returvaerdien er den fjerde tuple-
    indgang: ALLE kandidater (match eller ej) der har rigtige detaljer denne
    koersel -- caller (main()) skal upserte disse til DB, saa det arkitektur-
    hul lukkes hvor kun matches blev cachet tidligere.

    Udtrukket fra den oprindelige (Reshopper-specifikke) run_reshopper() ved
    G1 (DBA som ny kilde) -- selve fase 1/fase 2-logikken var identisk paa
    tvaers af kilder, kun kildenavnet og modulet skifter."""
    cached_details = cached_details or {}
    try:
        logger.info("=== Starter kilde: %s ===", source_name)
        search_config = dict(config)
        search_config["search_terms"] = build_search_terms(wishlist)
        logger.info("%s: soeger efter %d term(er): %s", source_name, len(search_config["search_terms"]), search_config["search_terms"])

        raw_listings = source_module.fetch(search_config, dry_run=dry_run)
        logger.info("%s: %d raa annonce(r) hentet", source_name, len(raw_listings))
        if not raw_listings:
            return [], [], True, []

        # Fase 1: billig foerfiltrering (pris/type/stoerrelse) FOER vi besoeger
        # en eneste annoncedetaljeside -- se matching.py:precheck().
        candidate_urls = []
        seen_urls = set()
        for listing in raw_listings:
            if listing["url"] in seen_urls:
                continue
            if any(matching.precheck(wl_item, listing) for wl_item in wishlist):
                candidate_urls.append(listing["url"])
                seen_urls.add(listing["url"])
        logger.info("%s: %d kandidat(er) efter foerfiltrering (af %d raa)", source_name, len(candidate_urls), len(raw_listings))

        if not candidate_urls:
            return [], [], True, []

        by_url = {l["url"]: l for l in raw_listings}

        # G10 (hastighedsoptimering): opdel kandidaterne i tre grupper FOER vi
        # kalder det dyre fetch_details():
        #   1. Kilder hvor fetch_details() er en BEVIDST no-op (Sellpy/Vinted,
        #      se de moduler) -- raa-kortet indeholder allerede ALLE detaljer
        #      (strukturelt signal: 'seller_name' findes allerede i kortets
        #      egen dict, modsat Reshopper/DBA hvor den KUN tilfoejes via
        #      fetch_details()). Disse skal aldrig i detalje-opslags-listen.
        #   2. Kandidater vi allerede har detalje-hentet succesfuldt i en
        #      TIDLIGERE koersel (samme id = hash(kilde+url), se
        #      db.cached_details_map()) -- genbruges direkte, INGEN
        #      netvaerkskald. Sparer 5-15s Playwright-throttling PR. kandidat
        #      for Reshopper/DBA.
        #   3. Resten -- helt nye kandidater, som stadig skal have det fulde
        #      fetch_details()-opslag.
        already_complete_urls = {url for url in candidate_urls if "seller_name" in by_url[url]}
        cache_hits: dict[str, dict] = {}
        new_detail_urls = []
        for url in candidate_urls:
            if url in already_complete_urls:
                continue
            cached = cached_details.get(db.make_id(source_name, url))
            if cached is not None:
                cache_hits[url] = cached
            else:
                new_detail_urls.append(url)

        logger.info(
            "%s: %d kandidat(er) i alt -- %d allerede komplette fra kortet, "
            "%d genbrugt fra detalje-cache, %d nye detalje-opslag noedvendige",
            source_name, len(candidate_urls), len(already_complete_urls),
            len(cache_hits), len(new_detail_urls),
        )

        # Fase 2: detalje-opslag KUN for de nye, ufordoejede kandidater.
        details_by_url = (
            source_module.fetch_details(new_detail_urls, search_config, dry_run=dry_run)
            if new_detail_urls else {}
        )

        enriched = []
        detail_cached_candidates = []
        for url in candidate_urls:
            listing = dict(by_url[url])
            details_ok = False
            if url in already_complete_urls:
                # Allerede fuldt beriget af fetch() selv -- intet at goere.
                details_ok = True
            elif url in cache_hits:
                # G10: genbrug brand/size/stand/seller_name/seller_id/
                # shipping_price fra et TIDLIGERE lykkedes detalje-opslag.
                # Prisen ('price') er IKKE del af cache_hits-dict'et og
                # forbliver derfor den friske vaerdi fra by_url ovenfor --
                # det er hele pointen, pris kan aendre sig og skal altid
                # afspejle det aktuelle soegeresultat.
                listing.update(cache_hits[url])
                details_ok = True
            else:
                detail = details_by_url.get(url)
                if detail:
                    listing.update(detail)
                    details_ok = True
                else:
                    # Detalje-opslag fejlede for denne ene annonce -- vi medtager den
                    # stadig, blot uden stand/saelger/fragt (markeres "ukendt" i
                    # matching.py's brand-tjek naar maerke er tomt paa oensket).
                    # IKKE cachet (details_ok forbliver False) -- forsoeges igen
                    # naeste koersel i stedet for at forblive "ukendt" for evigt.
                    listing.setdefault("stand", "ukendt")
                    listing.setdefault("seller_name", "ukendt")
                    listing.setdefault("seller_id", None)
                    listing.setdefault("shipping_price", None)
                    listing.setdefault("brand", None)
            listing["source"] = source_name
            enriched.append(listing)
            if details_ok:
                # G10-FIX (arkitektur-hul): gemmes UANSET om denne kandidat
                # ender med at matche noget oenske herunder -- ellers ville en
                # detalje-hentet ikke-match blive gen-hentet unoedigt igen og
                # igen. main() upserter denne liste til DB (details_fetched=1).
                detail_cached_candidates.append(dict(listing))

        matches = matching.match_all(wishlist, enriched)
        bundles = bundling.build_bundles(matches, config.get("bundling", {}).get("default_shipping_dkk", 39.0))
        return matches, bundles, True, detail_cached_candidates
    except Exception:
        logger.exception("%s: kilden fejlede, springer over -- resten af scriptet paavirkes ikke", source_name)
        return [], [], False, []


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Shopper -- Reshopper + DBA børnetøj-overvaagning")
    parser.add_argument("--dry-run", action="store_true", help="Koer uden at skrive til DB eller Sheets")
    parser.add_argument("--source", choices=list(SOURCE_MODULES.keys()), help="Koer kun én kilde (reshopper eller dba)")
    args = parser.parse_args()

    config = load_config()
    setup_logging(config.get("log_path", "monitor.log"))

    # os.setsid(): goer denne proces til sin egen session-/proces-GRUPPE-
    # leder, saa enhver Playwright-driver/Chromium-underproces den senere
    # spawner (sources/reshopper.py, sources/dba.py) som udgangspunkt arver
    # SAMME proces-gruppe. Det er forudsaetningen for at watchdog'ens
    # os.killpg(...)-nooedbremse (se hang_guard.py) rammer BAADE denne proces
    # OG dens Chromium-underprocesser i ét hug, i stedet for at efterlade
    # forældreloese/"zombie" Chromium-processer bagved (praecis den risiko
    # der blev tjekket for og IKKE fundet paa maskinen under denne haerdning,
    # men som vi ikke vil RISIKERE at skabe fremover). Fejler kaldet (fx fordi
    # processen allerede er sessionsleder, eller platformen ikke understoetter
    # det) er det harmloest -- watchdog'en falder da tilbage til et almindeligt
    # os._exit(1), som stadig dræber selve Python-processen.
    try:
        os.setsid()
    except Exception:
        logger.debug("os.setsid() fejlede/ikke noedvendigt (harmloest, ignoreres)", exc_info=True)

    # HAARD global watchdog (se hang_guard.py + DEFAULT_WATCHDOG_TIMEOUT_S
    # ovenfor) -- garanterer at DENNE proces aldrig kan koere laengere end
    # graensen, uanset hvordan den blev startet. .cancel() kaldes lige foer
    # HVER return-vej i main() nedenfor (kun to: den tidlige "ingen
    # oenskeseddel"-fejl og den normale slutning).
    watchdog_timeout_s = config.get("watchdog_timeout_s", DEFAULT_WATCHDOG_TIMEOUT_S)
    watchdog = hang_guard.install_hard_watchdog(watchdog_timeout_s, logger)
    logger.info("Watchdog: haard graense sat til %.0f min. for denne koersel", watchdog_timeout_s / 60.0)

    if args.dry_run:
        logger.info("--dry-run aktiv: skriver ikke til DB eller Sheets")

    # Sheets-klient + spreadsheet oprettes/aabnes FOER oenskesedlen indlaeses,
    # saa wishlist.source=sheet kan bruge samme spreadsheet som dashboardet.
    # G5-FIX (kritisk fund #1): Sheets-opsaetningen og Turso-config-load koerer
    # nu i TO HELT UAFHAENGIGE try/except-blokke. De laa tidligere i SAMME
    # try/except, hvilket betoed at en Sheets-fejl (fx forkert
    # credentials_file-sti) fik Python til at springe RESTEN af try-blokken
    # over -- inklusive turso_io.load_turso_config()/ensure_schema(), som intet
    # har med Sheets at goere. En Sheets-fejl maa ALDRIG forhindre at Turso
    # (og dermed webappen) faar sin config/skema paa plads, og omvendt.
    spreadsheet = None
    try:
        gs_cfg = config.get("google_sheets", {})
        client = sheets_output.get_sheets_client(gs_cfg["credentials_file"])
        spreadsheet = sheets_output.get_or_create_spreadsheet(client, config, allow_create=not args.dry_run)
    except Exception:
        logger.exception("Sheets: opsaetningen fejlede, fortsaetter uden Sheets-forbindelse")

    turso_url, turso_token = "", ""
    try:
        turso_cfg = config.get("turso", {})
        turso_url, turso_token = turso_io.load_turso_config(turso_cfg.get("secrets_path", "secrets.env"))
        if turso_url and turso_token:
            turso_io.ensure_schema(turso_url, turso_token)
    except Exception:
        logger.exception("Turso: opsaetningen fejlede (config-load og/eller skema), fortsaetter uden Turso")

    # G5: output-skrivning er en loekke over config["output"]["targets"] --
    # default ["sheet"] hvis noeglen mangler, for bagudkompatibilitet med
    # config.yaml-filer skrevet foer G5. Flyttet OP (var tidligere defineret
    # lige foer selve output-skrivningen nedenfor) fordi kilde-
    # fremdriftsindikatoren (se write_progress_status() nedenfor) ogsaa har
    # brug for at vide hvilke maal der er aktive, LAENGE foer output-
    # skrivningen finder sted.
    targets = config.get("output", {}).get("targets", ["sheet"])

    # Kilde-fremdriftsindikator: Kontrolpanel-fanen slaas op ÉN gang her (hvis
    # Sheets er et aktivt output-target) i stedet for for hver af de 4 kilders
    # fremdrifts-opdatering -- sparer unoedvendige gspread-kald. En fejl her er
    # ikke kritisk: control_ws forbliver None og write_progress_status()
    # springer Sheets-delen over.
    control_ws = None
    if "sheet" in targets and spreadsheet is not None:
        try:
            control_tab_name = config.get("trigger", {}).get("control_tab_name", "Kontrolpanel")
            control_ws = sheets_output.ensure_control_tab(spreadsheet, control_tab_name)
        except Exception:
            logger.warning("Sheets: kunne ikke aabne Kontrolpanel-fanen til kilde-fremdriftsstatus, springer over", exc_info=True)

    wishlist = wishlist_module.load_wishlist(config, spreadsheet=spreadsheet)
    if not wishlist:
        logger.error("Ingen oenskeseddel-items indlaest -- intet at soege efter. Stopper.")
        watchdog.cancel()
        return 1
    logger.info("Ønskeseddel: %d item(s): %s", len(wishlist), [
        f"{w['type']}/{w.get('maerke') or 'generisk'}/{w['stoerrelse']} (maks {w['maks_pris']} kr.)" for w in wishlist
    ])

    all_matches: list[dict] = []
    all_bundles: list[dict] = []
    # G5-FIX (fund #4): spor om MINDST ÉN kilde koerte igennem uden undtagelse
    # denne koersel. Bruges nedenfor til at afgoere om vi tor overskrive
    # Turso/Sheets med all_matches/all_bundles -- hvis ALLE kilder fejlede
    # (fx forbigaaende netvaerksfejl i run_source()), er all_matches/
    # all_bundles tomme af den forkerte grund ("alt fejlede", ikke "markedet
    # har reelt 0 matches"), og vi maa IKKE lade det se ud som en reel
    # generations-swap til 0 resultater.
    any_source_succeeded = False
    with db.connect(config.get("db_path", "seen.db")) as conn:
        first_seen_lookup = db.first_seen_map(conn)
        # G10 (hastighedsoptimering): laeses ÉN gang her i hovedtraaden FOER
        # kilderne startes parallelt nedenfor (ikke inde i hver worker-traad --
        # det ville betyde gentagne SQLite-kald for intet, da dict'et alligevel
        # er read-only for resten af koerslen). Gives som read-only parameter
        # til hver kildes run_source()-kald, se db.cached_details_map()'s
        # docstring for hvorfor samtidig laesning fra flere traade er sikkert.
        cached_details = db.cached_details_map(conn)
        logger.info("Detalje-cache: %d annonce(r) med genbrugelige detaljer fundet i %s", len(cached_details), config.get("db_path", "seen.db"))
        now_iso = datetime.datetime.utcnow().isoformat()

        sources_to_run = [args.source] if args.source else list(SOURCE_MODULES.keys())

        # Kilde-fremdriftsindikator: hvilke kilder er faerdige lige nu. Vises i
        # ALFABETISK raekkefoelge (konsistent uanset i hvilken raekkefoelge
        # kilderne reelt bliver faerdige -- typisk Sellpy/Vinted foerst, saa
        # DBA/Reshopper) saa brugeren ikke skal taenke over at raekkefoelgen
        # hopper rundt mellem koersler.
        completed_sources: set[str] = set()

        def progress_status_text() -> str:
            parts = [
                f"{SOURCE_DISPLAY_NAMES.get(n, n)} {'✓' if n in completed_sources else '…'}"
                for n in sorted(sources_to_run)
            ]
            return "Kører... (" + ", ".join(parts) + ")"

        def write_progress_status() -> None:
            """Skriver den loebende kilde-fremdriftsstatus til BAADE Sheets
            og Turso -- kun de maal der reelt er konfigureret i
            output.targets (samme moenster som selve output-skrivningen
            nedenfor). En fejl her (fx Sheets/Turso midlertidigt utilgaengelig)
            maa ALDRIG stoppe selve koerslen, kun logges som en advarsel."""
            if args.dry_run:
                return
            text = progress_status_text()
            if control_ws is not None:
                try:
                    sheets_output.set_status(control_ws, text)
                except Exception:
                    logger.warning("Sheets: kunne ikke skrive kilde-fremdriftsstatus (%r) -- fortsaetter koerslen", text, exc_info=True)
            if "turso" in targets and turso_url and turso_token:
                try:
                    turso_io.set_status(turso_url, turso_token, text)
                except Exception:
                    logger.warning("Turso: kunne ikke skrive kilde-fremdriftsstatus (%r) -- fortsaetter koerslen", text, exc_info=True)

        def write_final_status(text: str) -> None:
            """G13-FIX (UI-hul, ikke en proceshaengning): FOER denne rettelse
            skrev KUN trigger_watcher.py den endelige status (efter at have
            parset monitor.py's stdout NAAR den selv startede koerslen som
            subprocess). Koeres monitor.py DIREKTE (test, ad-hoc, eller et
            fremtidigt planlagt job udenom trigger_watcher.py) blev status
            derfor staaende paa sidste fremdrifts-tekst ('Kører... (X ✓, Y …)')
            for evigt -- UANSET om koerslen reelt lykkedes fint. Set fra en
            bruger der kigger paa Kontrolpanelet/webappen er det umuligt at
            skelne fra en reel haengning. monitor.py skriver derfor nu ALTID
            sin egen endelige status her, saa den er selvbaerende uanset
            hvordan den bliver kaldt -- trigger_watcher.py's finish_run()
            overskriver den blot med samme/lignende tekst bagefter naar den
            selv er den der startede koerslen, hvilket er harmloest."""
            if args.dry_run:
                return
            if control_ws is not None:
                try:
                    sheets_output.set_status(control_ws, text)
                except Exception:
                    logger.warning("Sheets: kunne ikke skrive endelig status (%r)", text, exc_info=True)
            if "turso" in targets and turso_url and turso_token:
                try:
                    turso_io.set_status(turso_url, turso_token, text)
                except Exception:
                    logger.warning("Turso: kunne ikke skrive endelig status (%r)", text, exc_info=True)

        try:
            write_progress_status()  # initial status foer nogen kilde er faerdig
        except Exception:
            logger.warning("Kunne ikke skrive indledende kilde-fremdriftsstatus -- fortsaetter koerslen", exc_info=True)

        # G6 (hastighedsoptimering): de 4 kilder koeres nu SAMTIDIGT i stedet
        # for sekventielt -- hver kildes fetch()/fetch_details() er allerede
        # uafhaengig (egen Playwright-browser-instans hhv. HTTP-session pr.
        # kilde, se sources/reshopper.py, sources/dba.py, sources/sellpy.py,
        # sources/vinted.py) og deler kun wishlist/config, som KUN LAESES,
        # aldrig skrives, af run_source(). Reshopper og DBAs 5-15s tilfaeldige
        # detalje-opslags-throttling var hovedaarsagen til at en fuld koersel
        # tog 14+ minutter sekventielt -- naar de i stedet overlapper i tid
        # falder den samlede tid til ca. den LANGSOMSTE enkeltkilde, ikke
        # summen af alle fire. VIGTIGT: dette aendrer INTET ved den enkelte
        # kildes egen kadence/throttling -- hver kilde venter stadig sin egen
        # min_delay_s/max_delay_s mellem sine egne detalje-opslag, akkurat som
        # naar den koerer alene.
        #
        # sqlite3-forbindelser er IKKE traadsikre, saa selve DB-upsertet
        # (conn) sker udelukkende i hovedtraaden nedenfor, EFTER hver kildes
        # Future bliver faerdig via as_completed() -- aldrig inde i en
        # worker-traad.
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(sources_to_run))) as executor:
            future_to_name = {}
            for name in sources_to_run:
                source_module = SOURCE_MODULES.get(name)
                if source_module is None:
                    logger.warning("Ukendt kilde konfigureret: %s, springer over", name)
                    continue
                future = executor.submit(run_source, name, source_module, config, wishlist, args.dry_run, cached_details)
                future_to_name[future] = name

            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    matches, bundles, source_ok, detail_candidates = future.result()
                except Exception:
                    # Ekstra sikkerhedsnet: run_source() fanger allerede ALLE
                    # exceptions internt og returnerer ([], [], False, []), saa
                    # denne gren boer reelt aldrig ramme -- men en Future maa
                    # under ingen omstaendigheder kunne vaelte resten af
                    # koerslen, heller ikke ved en helt uforudset fejl (fx i
                    # selve ThreadPoolExecutor-maskineriet).
                    logger.exception("%s: uventet fejl i kilde-future (boer ikke kunne ske, run_source() fanger internt) -- springer over", name)
                    matches, bundles, source_ok, detail_candidates = [], [], False, []

                if source_ok:
                    any_source_succeeded = True

                # G10-FIX (arkitektur-hul): baseline-cache ALLE detalje-hentede
                # kandidater fra denne kilde -- UANSET om de ender med at
                # matche noget oenske i loopet herunder. Skrives FOER
                # matches-loopet, saa et EVENTUELT reelt match kan overskrive
                # match_rank/wishlist_*-felterne med de rigtige vaerdier lige
                # bagefter (se db.py's ON CONFLICT-logik og upsert_listing()'s
                # docstring) -- uden dette ville en kandidat der blev
                # detalje-hentet men IKKE matchede noget oenske ALDRIG blive
                # gemt, og derfor blive detalje-hentet unoedigt igen og igen.
                for c in detail_candidates:
                    listing_id = db.make_id(c.get("source", name), c["url"])
                    row = {
                        "id": listing_id,
                        "source": c.get("source", name),
                        "item_id": c.get("item_id"),
                        "title": c.get("title"),
                        "brand": c.get("brand"),
                        "size": c.get("size"),
                        "price": c.get("price"),
                        "stand": c.get("stand"),
                        "seller_name": c.get("seller_name"),
                        "seller_id": c.get("seller_id"),
                        "shipping_price": c.get("shipping_price"),
                        "url": c.get("url"),
                        "match_rank": None,
                        "wishlist_type": None,
                        "wishlist_maerke": None,
                        "wishlist_stoerrelse": None,
                        "first_seen": first_seen_lookup.get(listing_id, now_iso),
                        "last_seen": now_iso,
                        "details_fetched": 1,
                    }
                    db.upsert_listing(conn, row, dry_run=args.dry_run)
                    first_seen_lookup[listing_id] = row["first_seen"]

                for m in matches:
                    listing_id = db.make_id(m.get("source", name), m["url"])
                    m["_db_id"] = listing_id
                    row = {
                        "id": listing_id,
                        "source": m.get("source", name),
                        "item_id": m.get("item_id"),
                        "title": m.get("title"),
                        "brand": m.get("brand"),
                        "size": m.get("size"),
                        "price": m.get("price"),
                        "stand": m.get("stand"),
                        "seller_name": m.get("seller_name"),
                        "seller_id": m.get("seller_id"),
                        "shipping_price": m.get("shipping_price"),
                        "url": m.get("url"),
                        "match_rank": m.get("match_rank"),
                        "wishlist_type": m.get("wishlist_type"),
                        "wishlist_maerke": m.get("wishlist_maerke"),
                        "wishlist_stoerrelse": m.get("wishlist_stoerrelse"),
                        "first_seen": first_seen_lookup.get(listing_id, now_iso),
                        "last_seen": now_iso,
                        # Et match er pr. definition detalje-hentet (ellers kunne
                        # matching.py ikke have bekraeftet maerke/pris) -- markeres
                        # ogsaa her, redundant men harmloest ift. baseline-loopet
                        # ovenfor (samme id, samme vaerdi).
                        "details_fetched": 1,
                    }
                    db.upsert_listing(conn, row, dry_run=args.dry_run)
                    # Opdatér lookup'en saa ogsaa NYE items (foerste gang set i denne
                    # koersel) har korrekt first_seen tilgaengeligt til Sheets/CSV-output
                    # nedenfor, ikke kun items der allerede fandtes i seen.db.
                    first_seen_lookup[listing_id] = row["first_seen"]

                all_matches.extend(matches)
                all_bundles.extend(bundles)

                completed_sources.add(name)
                try:
                    write_progress_status()
                except Exception:
                    logger.warning("Kunne ikke opdatere kilde-fremdriftsstatus efter %s -- fortsaetter koerslen", name, exc_info=True)

    now_str = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
    logger.info("=== Samlet resultat: %d match(es), %d saelger-bundle(s) ===", len(all_matches), len(all_bundles))

    # G5: output-skrivning er en loekke over config["output"]["targets"] --
    # default ["sheet"] hvis noeglen mangler, for bagudkompatibilitet med
    # config.yaml-filer skrevet foer G5. "sheet"-grenen er 100% UAENDRET
    # (samme kode/CSV-fallback som altid). "turso"-grenen er NY og koerer i
    # sit EGET try/except -- en Turso-fejl maa ALDRIG paavirke Sheets-output
    # eller omvendt. (`targets` er defineret laengere oppe i main(), foer
    # kilde-fremdriftsindikatoren, som ogsaa har brug for den.)

    # G5-FIX (fund #4): hvis ALLE konfigurerede kilder fejlede med en
    # undtagelse denne koersel (ingen af dem naaede at koere igennem), er
    # all_matches/all_bundles tomme fordi scraping'en fejlede -- IKKE fordi
    # markedet reelt har 0 matches lige nu. At skrive dette til Turso/Sheets
    # ville trigge generations-swap'en (se turso_io.py) og slette al
    # eksisterende data pga. en forbigaaende netvaerksfejl. Vi springer derfor
    # HELE output-skrivningen (Sheets OG Turso) over og logger en tydelig
    # advarsel i stedet.
    if not sources_to_run:
        logger.warning("Ingen kilder blev konfigureret til at koere denne gang -- springer output-skrivning over")
        write_final_status("Fejlede: ingen kilder konfigureret i config.yaml")
    elif not any_source_succeeded:
        logger.warning(
            "ALLE konfigurerede kilder (%s) fejlede denne koersel (0 lykkedes) -- springer output-skrivning til "
            "Sheets/Turso/CSV over for at undgaa at overskrive eksisterende data med tomme resultater. "
            "Se ovenstaaende exception(s) for detaljer.",
            ", ".join(sources_to_run),
        )
        write_final_status(f"Fejlede kl. {now_str} -- alle kilder ({', '.join(sources_to_run)}) fejlede, se monitor.log")
    elif args.dry_run:
        logger.info("--dry-run: skriver ikke til Sheets/Turso/CSV-fallback")
    else:
        for target in targets:
            if target == "sheet":
                if spreadsheet is not None:
                    try:
                        sheets_output.write_matches(spreadsheet, all_matches, first_seen_lookup, now_str)
                        sheets_output.write_bundles(spreadsheet, all_bundles, now_str)
                        logger.info("FAERDIG -- dashboard opdateret: %s", spreadsheet.url)
                    except Exception:
                        logger.exception("Sheets: kunne ikke skrive resultater, falder tilbage til lokal CSV")
                        sheets_output.write_local_csv_fallback(all_matches, all_bundles, first_seen_lookup)
                else:
                    sheets_output.write_local_csv_fallback(all_matches, all_bundles, first_seen_lookup)
            elif target == "turso":
                try:
                    if turso_url and turso_token:
                        tldr_text = sheets_output.build_tldr_line(all_bundles)
                        n_matches, n_bundles = turso_io.write_matches_and_bundles(
                            turso_url, turso_token, all_matches, all_bundles,
                            first_seen_lookup, now_iso, tldr_text,
                        )
                        logger.info("Turso FAERDIG -- %d match(es), %d bundle(s) skrevet", n_matches, n_bundles)
                    else:
                        logger.warning("Turso: output.targets indeholder 'turso' men credentials mangler i secrets.env -- springer over")
                except Exception:
                    logger.exception("Turso: kunne ikke skrive resultater (Sheets-sporet ovenfor er upaavirket af dette)")
            else:
                logger.warning("output.targets: ukendt maal %r, springer over", target)

        # G13-FIX: skriv den endelige "Færdig"-status HERFRA (se
        # write_final_status()'s docstring) -- IKKE kun via
        # trigger_watcher.py's efterfoelgende stdout-parsing, som ikke koerer
        # naar monitor.py kaldes direkte/ad-hoc.
        write_final_status(f"Færdig kl. {now_str} ({len(all_matches)} matches, {len(all_bundles)} bundles)")

    watchdog.cancel()
    return 0


if __name__ == "__main__":
    sys.exit(main())
