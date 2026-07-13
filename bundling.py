"""Bundling: gruppér matches pr. saelger og beregn fragt-oekonomi. Se
personal-shopper-brief.md §6 -- dette er kernen i businesscasen.

Kerneidé: én saelger, flere matchende items -> ÉN fragt for hele koebet i
stedet for én fragt pr. item. Effektiv pris/stk falder markant naar man kan
samle flere smaa/billige items hos samme saelger (brief-eksempel: 4 bodyer
à 20 kr. + 45 kr. fragt = 26 kr./stk. i stedet for 65 kr./stk. hver for sig).
"""
import logging
from collections import defaultdict

logger = logging.getLogger("personal_shopper.bundling")

# J5 (kritikrunde 2026-07-10): kilder hvor "bundling pr. sælger" IKKE giver
# mening, fordi seller_name er en kunstig, hardcodet konstant fremfor en
# rigtig individuel sælger (se fx sources/sellpy.py: Sellpy er konsignation,
# ALT saettes til seller_name="Sellpy"). Uden denne udelukkelse ville
# usammenhaengende items (fx leggings+duplo+jakke fra vidt forskellige
# reelle saelgere) kollapse til én kunstig "bundle" der naesten altid
# "betaler sig", og udvande signalet. Saet som en modul-konstant (ikke
# hardcodet dybt i logikken nedenfor) saa fremtidige konsignations-kilder
# er lette at tilføje her uden at røre selve bundle-algoritmen.
NON_BUNDLEABLE_SOURCES = {"sellpy"}

# G30: minimum antal manuelt indsamlede fragt-observationer for et land FOER
# et landegennemsnit bruges som et estimat i stedet for at vise "ukendt" --
# SAMME graense som turso_io.MIN_SHIPPING_OBSERVATIONS (duplikeret her, ikke
# importeret, for at bundling.py forbliver en ren funktion uden Turso-
# afhaengighed -- den modtager blot allerede-hentede tal som argument).
MIN_SHIPPING_OBSERVATIONS = 10


def _seller_key(match: dict) -> str:
    """Saelger-ID hvis vi kunne udtraekke det (se sources/reshopper.py og
    sources/dba.py), ellers saelgernavn som fallback-groupnoegle (IKKE
    garanteret unikt paa tvaers af én platform -- flere saelgere kan dele
    fornavn+forbogstav -- men bedste tilgaengelige signal naar det
    best-effort ID-udtraek fejler).

    VIGTIGT (G1, DBA-tilfoejelse): noeglen praefikses ALTID med kilden.
    En Reshopper-saelger og en DBA-saelger med samme navn (eller endda
    samme numeriske ID paa hver deres platform, rent tilfaeldigt) er IKKE
    noedvendigvis samme person -- de har adskilte konti paa adskilte
    platforme, saa bundling paa tvaers af kilder ville foreslaa at samle
    et koeb hos "én saelger" der reelt kraever to separate handler/fragter."""
    source = (match.get("source") or "ukendt_kilde").strip().lower()
    seller_id = match.get("seller_id")
    if seller_id:
        return f"{source}|id:{seller_id}"
    return f"{source}|navn:{(match.get('seller_name') or 'ukendt').strip().lower()}"


def apply_shipping_estimates(matches: list[dict], country_shipping_estimates: dict | None) -> None:
    """G30: beriger matches IN-PLACE med 'shipping_price_estimate'/
    'shipping_price_estimate_count' -- KUN naar den reelle 'shipping_price'
    er ukendt, saelgerlandet er kendt og udenlandsk, og landet har mindst
    MIN_SHIPPING_OBSERVATIONS manuelt indsamlede observationer (se
    turso_io.get_shipping_estimates()). Koeres FOER build_bundles(), saa
    BAADE individuelle matches (Matches-listen, enkelt-item-saelgere) OG
    bundles (via samme grundlag) konsekvent viser samme landegennemsnit --
    'shipping_price' (det bekraeftede felt) roeres ALDRIG, kun det nye,
    adskilte estimat-felt tilfoejes."""
    for m in matches:
        m.setdefault("shipping_price_estimate", None)
        m.setdefault("shipping_price_estimate_count", None)
        if not country_shipping_estimates:
            continue
        if m.get("shipping_price") is not None:
            continue  # allerede en bekraeftet pris -- intet estimat noedvendigt
        country = m.get("seller_country")
        if not country or country == "DK":
            continue
        candidate = country_shipping_estimates.get(country)
        if candidate and candidate.get("count", 0) >= MIN_SHIPPING_OBSERVATIONS:
            m["shipping_price_estimate"] = candidate["avg"]
            m["shipping_price_estimate_count"] = candidate["count"]


def build_bundles(
    matches: list[dict], default_shipping_dkk: float = 39.0,
    country_shipping_estimates: dict | None = None,
) -> list[dict]:
    """Grupperer matches pr. saelger og beregner bundle-oekonomi.
    Returnerer bundle-dicts sorteret efter stoerst besparelse pr. item foerst.

    J5: matches fra NON_BUNDLEABLE_SOURCES (fx Sellpy, konsignation) danner
    ALDRIG en bundle, uanset antal -- de springes over her og optraeder
    derfor KUN i Matches-listen (all_matches), aldrig i Bundles. Se
    modulets NON_BUNDLEABLE_SOURCES-konstant og BACKLOG.md's J5-fund.

    G30: 'country_shipping_estimates' er et valgfrit {land: {"avg", "count"}}
    -dict (se turso_io.get_shipping_estimates()) af manuelt indsamlede fragt-
    observationer. None (default) bevarer PRAECIS G21-fixets adfaerd
    (kendt udenlandsk saelger uden reel fragt -> "ukendt", ingen antagelse).
    Naar dict'et ER givet OG landet har >= MIN_SHIPPING_OBSERVATIONS: bruges
    landegennemsnittet som et EKSPLICIT maerket estimat (adskilt fra et
    bekraeftet 'shipping_price' og fra den danske 'default_shipping_dkk'-
    antagelse) -- se 'shipping_is_country_estimate' i det returnerede dict."""
    by_seller = defaultdict(list)
    for m in matches:
        source = (m.get("source") or "").strip().lower()
        if source in NON_BUNDLEABLE_SOURCES:
            continue
        by_seller[_seller_key(m)].append(m)

    bundles = []
    for seller_key, seller_matches in by_seller.items():
        # Dedupliker paa item_id -- samme fysiske annonce kan optraede flere
        # gange hvis den matcher flere oenskeseddel-raekker (se matching.py).
        unique_items = {}
        for m in seller_matches:
            unique_items.setdefault(m.get("item_id") or m.get("url"), m)
        items = list(unique_items.values())
        count = len(items)
        if count == 0:
            continue

        shipping_values = [m.get("shipping_price") for m in items if m.get("shipping_price") is not None]
        # G21-FIX (kritisk fund): default_shipping_dkk er en DANSK indenrigs-
        # antagelse -- den er BEKRAEFTET forkert for kendte udenlandske
        # saelgere (live-testet mod en rigtig finsk saelger, se BACKLOG.md's
        # G21). Uden en rigtig Vinted-login-session (G22) har vi INTET
        # paalideligt tal for disse -- vi GAETTER derfor IKKE et andet tal,
        # vi viser aerligt "ukendt" fremfor et selvsikkert men sandsynligt
        # forkert "betaler sig"-facit (samme princip som G6/G16/G20).
        known_countries = {m.get("seller_country") for m in items if m.get("seller_country")}
        is_known_foreign = bool(known_countries) and known_countries != {"DK"}

        # G30: landegennemsnit -- KUN relevant naar vi IKKE allerede har en
        # bekraeftet fragtpris, og saelgeren er et KENDT enkelt udenlandsk
        # land (en bundle er altid samme saelger, saa known_countries har
        # hoejst ét element her naar is_known_foreign er True).
        country_estimate = None
        country_estimate_count = 0
        if country_shipping_estimates and is_known_foreign:
            country = next(iter(known_countries))
            candidate = country_shipping_estimates.get(country)
            if candidate and candidate.get("count", 0) >= MIN_SHIPPING_OBSERVATIONS:
                country_estimate = candidate["avg"]
                country_estimate_count = candidate["count"]

        shipping_is_country_estimate = False
        if shipping_values:
            # Fragt er pr. ORDRE, ikke pr. item -- vi antager saelgerens fragtpris
            # er ens paa tvaers af egne annoncer. Bruger den hoejeste observerede
            # vaerdi som et konservativt (ikke-optimistisk) bud paa den reelle pris.
            shipping = max(shipping_values)
            shipping_is_assumed = False
        elif country_estimate is not None:
            # G30: manuelt indsamlet landegennemsnit -- IKKE en bekraeftet
            # pris for DENNE specifikke saelger, men et data-baseret estimat
            # (min. MIN_SHIPPING_OBSERVATIONS observationer), langt mere
            # praecist end den tidligere danske 39kr-antagelse ville have
            # vaeret for en udenlandsk saelger.
            shipping = country_estimate
            shipping_is_assumed = False
            shipping_is_country_estimate = True
        elif is_known_foreign:
            shipping = None
            shipping_is_assumed = False
        else:
            shipping = default_shipping_dkk
            shipping_is_assumed = True

        total_item_price = sum(m["price"] for m in items)
        if shipping is not None:
            total_with_shipping = round(total_item_price + shipping, 2)
            effective_price_per_item = round(total_with_shipping / count, 2)
            alone_price_per_item = round(sum(m["price"] + shipping for m in items) / count, 2)
            savings_per_item = round(alone_price_per_item - effective_price_per_item, 2)
            bundle_worth_it = count >= 2
        else:
            # Ukendt fragt for en kendt udenlandsk saelger -- INGEN af disse
            # tal kan beregnes aerligt, og "betaler sig" forbliver bevidst
            # False (ikke None) saa eksisterende booleanske forbrugere
            # (Sheets/webapp/TL;DR-taelling) ikke kraever aendring for at
            # haandtere en tredje tilstand -- konservativt "nej" er sikrere
            # end at fejlagtigt paastaa et "ja" vi ikke kan bakke op med tal.
            total_with_shipping = None
            effective_price_per_item = None
            alone_price_per_item = None
            savings_per_item = None
            bundle_worth_it = False

        bundles.append({
            "seller_key": seller_key,
            "source": items[0].get("source", "ukendt_kilde"),
            "seller_name": items[0].get("seller_name", "ukendt"),
            "seller_id": items[0].get("seller_id"),
            "item_count": count,
            "items": items,
            "total_item_price": round(total_item_price, 2),
            "shipping_dkk": shipping,
            "shipping_is_assumed": shipping_is_assumed,
            "shipping_is_country_estimate": shipping_is_country_estimate,
            "shipping_estimate_count": country_estimate_count if shipping_is_country_estimate else None,
            "shipping_unknown_foreign": is_known_foreign and shipping is None,
            "total_with_shipping": total_with_shipping,
            "effective_price_per_item": effective_price_per_item,
            "alone_price_per_item": alone_price_per_item,
            "savings_per_item": savings_per_item,
            "bundle_worth_it": bundle_worth_it,
            # Lokal afhentning-bonus: KUN naar vi har positiv bekraeftelse af 0-kr
            # fragt fra schema.org-dataen -- manglende fragt-info er IKKE det samme
            # som bekraeftet gratis afhentning (kan ogsaa vaere manglende data).
            # G30: et estimat kan (i teorien, ekstremt usandsynligt) ramme
            # praecis 0 -- udelukkes eksplicit her, da "gratis fragt" kun
            # boer vises ved en BEKRAEFTET 0-kr-pris, aldrig et gennemsnit.
            "local_pickup_bonus": (not shipping_is_assumed) and (not shipping_is_country_estimate) and shipping == 0,
        })

    # En "bundle" giver kun mening med 2+ items -- ellers er der ingen delt
    # fragt at spare, og det er reelt bare et enkelt match (som allerede staar
    # i Matches-listen). Enkelt-item-saelgere frafiltreres her, saa
    # bundle-tallet baade i webappen, Sheets og status-teksten er ægte antal
    # bundles (Esben-oenske 2026-07-10). Enkelt-matchene mistes IKKE -- de er
    # stadig i all_matches / Matches-visningen.
    sellers_with_match = len(bundles)
    bundles = [b for b in bundles if b["item_count"] >= 2]
    # G21-FIX: savings_per_item kan nu vaere None (kendt udenlandsk saelger,
    # ukendt fragt) -- disse sorteres bagerst (ikke foerst pga. -None-crash),
    # da vi netop IKKE kan bekraefte en besparelse for dem.
    bundles.sort(key=lambda b: (
        b["savings_per_item"] is None,
        -b["savings_per_item"] if b["savings_per_item"] is not None else 0,
        -b["item_count"],
    ))
    logger.info(
        "Bundling: %d saelger(e) med mindst ét match, heraf %d ægte bundle(s) (2+ items)",
        sellers_with_match, len(bundles),
    )
    return bundles
