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
import datetime
import logging
import logging.handlers
import sys

import yaml

import bundling
import db
import matching
import sheets_output
import turso_io
import wishlist as wishlist_module
from sources import dba, reshopper, sellpy

SOURCE_MODULES = {
    "reshopper": reshopper,
    "dba": dba,
    "sellpy": sellpy,
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


def run_source(source_name: str, source_module, config: dict, wishlist: list[dict], dry_run: bool) -> tuple[list[dict], list[dict], bool]:
    """Koerer én kilde (reshopper ELLER dba -- begge foelger samme to-fase-
    fetch()/fetch_details()-kontrakt, se sources/reshopper.py og
    sources/dba.py) i eget try/except -- en fejl her maa aldrig vaelte
    resten af scriptet (samme princip som PA SPEAKERS-arkivets
    monitor.py:run_source). Returnerer (matches, bundles, ok) -- tomme lister
    og ok=False hvis kilden fejler helt (undtagelse undervejs), ok=True hvis
    kilden koerte igennem uden undtagelse (ogsaa hvis den reelt fandt 0
    matches -- det er en gyldig markedstilstand, ikke en fejl). G5-FIX
    (fund #4): denne ok-status bruges af main() til at skelne "koerte, fandt
    0" fra "fejlede helt", saa vi ikke fejlagtigt overskriver Turso/Sheets med
    tomme resultater naar ALLE kilder reelt bare fejlede (fx forbigaaende
    netvaerksfejl).

    Udtrukket fra den oprindelige (Reshopper-specifikke) run_reshopper() ved
    G1 (DBA som ny kilde) -- selve fase 1/fase 2-logikken var identisk paa
    tvaers af kilder, kun kildenavnet og modulet skifter."""
    try:
        logger.info("=== Starter kilde: %s ===", source_name)
        search_config = dict(config)
        search_config["search_terms"] = build_search_terms(wishlist)
        logger.info("%s: soeger efter %d term(er): %s", source_name, len(search_config["search_terms"]), search_config["search_terms"])

        raw_listings = source_module.fetch(search_config, dry_run=dry_run)
        logger.info("%s: %d raa annonce(r) hentet", source_name, len(raw_listings))
        if not raw_listings:
            return [], [], True

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
            return [], [], True

        # Fase 2: detalje-opslag KUN for kandidater -- saelger/stand/fragt.
        details_by_url = source_module.fetch_details(candidate_urls, search_config, dry_run=dry_run)

        by_url = {l["url"]: l for l in raw_listings}
        enriched = []
        for url in candidate_urls:
            listing = dict(by_url[url])
            detail = details_by_url.get(url)
            if detail:
                listing.update(detail)
            else:
                # Detalje-opslag fejlede for denne ene annonce -- vi medtager den
                # stadig, blot uden stand/saelger/fragt (markeres "ukendt" i
                # matching.py's brand-tjek naar maerke er tomt paa oensket).
                listing.setdefault("stand", "ukendt")
                listing.setdefault("seller_name", "ukendt")
                listing.setdefault("seller_id", None)
                listing.setdefault("shipping_price", None)
                listing.setdefault("brand", None)
            listing["source"] = source_name
            enriched.append(listing)

        matches = matching.match_all(wishlist, enriched)
        bundles = bundling.build_bundles(matches, config.get("bundling", {}).get("default_shipping_dkk", 39.0))
        return matches, bundles, True
    except Exception:
        logger.exception("%s: kilden fejlede, springer over -- resten af scriptet paavirkes ikke", source_name)
        return [], [], False


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Shopper -- Reshopper + DBA børnetøj-overvaagning")
    parser.add_argument("--dry-run", action="store_true", help="Koer uden at skrive til DB eller Sheets")
    parser.add_argument("--source", choices=list(SOURCE_MODULES.keys()), help="Koer kun én kilde (reshopper eller dba)")
    args = parser.parse_args()

    config = load_config()
    setup_logging(config.get("log_path", "monitor.log"))

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

    wishlist = wishlist_module.load_wishlist(config, spreadsheet=spreadsheet)
    if not wishlist:
        logger.error("Ingen oenskeseddel-items indlaest -- intet at soege efter. Stopper.")
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
        now_iso = datetime.datetime.utcnow().isoformat()

        sources_to_run = [args.source] if args.source else list(SOURCE_MODULES.keys())
        for name in sources_to_run:
            source_module = SOURCE_MODULES.get(name)
            if source_module is None:
                logger.warning("Ukendt kilde konfigureret: %s, springer over", name)
                continue
            matches, bundles, source_ok = run_source(name, source_module, config, wishlist, args.dry_run)
            if source_ok:
                any_source_succeeded = True

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
                }
                db.upsert_listing(conn, row, dry_run=args.dry_run)
                # Opdatér lookup'en saa ogsaa NYE items (foerste gang set i denne
                # koersel) har korrekt first_seen tilgaengeligt til Sheets/CSV-output
                # nedenfor, ikke kun items der allerede fandtes i seen.db.
                first_seen_lookup[listing_id] = row["first_seen"]

            all_matches.extend(matches)
            all_bundles.extend(bundles)

    now_str = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
    logger.info("=== Samlet resultat: %d match(es), %d saelger-bundle(s) ===", len(all_matches), len(all_bundles))

    # G5: output-skrivning er en loekke over config["output"]["targets"] --
    # default ["sheet"] hvis noeglen mangler, for bagudkompatibilitet med
    # config.yaml-filer skrevet foer G5. "sheet"-grenen er 100% UAENDRET
    # (samme kode/CSV-fallback som altid). "turso"-grenen er NY og koerer i
    # sit EGET try/except -- en Turso-fejl maa ALDRIG paavirke Sheets-output
    # eller omvendt.
    targets = config.get("output", {}).get("targets", ["sheet"])

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
    elif not any_source_succeeded:
        logger.warning(
            "ALLE konfigurerede kilder (%s) fejlede denne koersel (0 lykkedes) -- springer output-skrivning til "
            "Sheets/Turso/CSV over for at undgaa at overskrive eksisterende data med tomme resultater. "
            "Se ovenstaaende exception(s) for detaljer.",
            ", ".join(sources_to_run),
        )
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
