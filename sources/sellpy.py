"""Sellpy.dk (G8): ny match-kilde via ÉT offentligt Algolia-kald pr. soegeterm.

G8-spike (BACKLOG.md, 2026-07-10) bekraeftet med rigtige kald 2026-07-10:
  - INGEN browser, INGEN login, INGEN bot-wall (modsat Reshopper/DBA). robots.txt
    er permissiv (Allow: /). Al data ligger allerede i Algolia-soegehittet, saa
    denne kilde behoever IKKE et separat detalje-opslag (fetch_details er en
    tynd no-op, se nederst).
  - Offentligt Algolia multi-query-endpoint:
      POST https://3lxsu2dn7t-dsn.algolia.net/1/indexes/*/queries
      Headers: x-algolia-application-id: 3LXSU2DN7T
               x-algolia-api-key: 380077912d5cdc2bebf67d4b4ad10a30 (dansk soege-key)
               Content-Type: application/json
      Body: {"requests":[{"indexName":"prod_marketItem_da_relevance",
             "params":"query=<URL-encoded term>&hitsPerPage=<N>"}]}
    Index 'prod_marketItem_da_relevance' -- IKKE '_saleStartedAt_desc' (gav
    solgte varer uden pris, se BACKLOG.md).
  - BEKRAEFTEDE feltstier i hvert hit (verificeret mod query "Birkholm leggings"
    og "Zara bukser" 2026-07-10):
      objectID              -> stabilt item-ID; item-URL = sellpy.dk/item/<objectID>
      price_DK.amount        -> pris i ØRE (heltal, fx 2500) -- divideres med 100
      metadata.brand         -> maerke (fx "Birkholm")
      metadata.type          -> vare-type (fx "Leggings", "Bukser")
      metadata.size          -> stoerrelse, boernetoej i cm-format ("CHILD-CM-80",
                                 "CHILD-CM-98/104"); voksen/andet i anden skala
                                 ("WMN-INT-S") -- vi PARSER cm-tallet ud (foerste
                                 tal ved interval, se _parse_cm_size); ikke-cm-
                                 stoerrelser giver "" (tom stoerrelse).
                                 J7-PRAECISERING (doc-rot fundet i kritikrunde
                                 2026-07-10): dette udelukker KUN voksentoej
                                 naar oensket rent faktisk HAR en stoerrelse
                                 angivet -- matching._size_rank behandler tom
                                 stoerrelse som "stoerrelse er ikke et kriterie"
                                 (G7). For et STOERRELSESLOEST oenske (fx et
                                 legetoejs-oenske uden cm-stoerrelse) matcher en
                                 voksen Sellpy-vare SAA LAENGE type+pris passer
                                 -- der er INGEN generel voksentoejs-udelukkelse,
                                 kun en udelukkelse betinget af at oensket har
                                 en numerisk stoerrelse at sammenligne med.
      metadata.condition     -> dansk stand ("Nyt"/"Meget god"/"God"/"Acceptabelt")
      isOnShelf (bool)       -> KUN true medtages; resten er solgt/reserveret.
      segment                -> fx "children" (boernetoej) / "women" osv.

Sellpy er en KONSIGNATIONSmodel: alle varer sendes af Sellpy selv med faelles
fragt, ikke af individuelle saelgere. Vi saetter derfor seller_name="Sellpy"
konsekvent (seller_id=None). J5-FIX (kritikrunde 2026-07-10): netop FORDI
"Sellpy" ikke er en rigtig individuel saelger, ville bundling.py ellers
kollapse usammenhaengende Sellpy-fund (fx leggings+duplo+jakke) til én
kunstig "bundle" der naesten altid "betaler sig" og udvander signalet --
bundling.py's NON_BUNDLEABLE_SOURCES udelukker derfor "sellpy" fra
bundle-dannelse helt. Sellpy-matches optraeder KUN i Matches-listen, aldrig
i Bundles. Fragtprisen er faelles/ukendt fast vaerdi -> shipping_price=None
(irrelevant for bundling naar kilden alligevel er udelukket derfra).

Fejler ALDRIG hele scriptet: netvaerks-/parsefejl logges og giver blot en tom
liste (eller springer det enkelte hit over), aldrig en undtagelse op i monitor.py.
"""
import json
import logging
import re
from urllib.parse import quote

logger = logging.getLogger("personal_shopper.sellpy")

# G16: signalerer eksplicit til monitor.py's run_source() at fetch_details()
# er en AEGTE no-op for denne kilde -- kandidater kan trygt springe HELE
# detalje-fasen over (ingen ekstra HTTP-kald noedvendig). Modsat Vinted, hvor
# fetch_details() nu goer reelt arbejde (land-opslag), saa den IKKE kan
# springes over paa samme maade. Manglende attribut paa et kildemodul
# tolkes som False (skal IKKE springes over) -- se monitor.py:run_source().
SKIP_DETAIL_FETCH = True

ALGOLIA_URL = "https://3lxsu2dn7t-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_APP_ID = "3LXSU2DN7T"
# Offentlig, klient-side dansk SOEGE-key (search-only, samme som Sellpy.dk's egen
# frontend bruger) -- ikke en hemmelig admin-key, derfor ok hardcodet her (samme
# princip som Reshopper/DBA's hardcodede URL'er).
ALGOLIA_API_KEY = "380077912d5cdc2bebf67d4b4ad10a30"
ALGOLIA_INDEX = "prod_marketItem_da_relevance"

ITEM_URL_TMPL = "https://www.sellpy.dk/item/{object_id}"

# Tal-gruppe(r) efter "CM-" i en Sellpy-stoerrelse. Ved interval-stoerrelser
# ("CHILD-CM-98/104") BEVARER vi nu begge tal som "98/104" (G15, 2026-07-10 --
# foer G15 tog vi bevidst kun det foerste tal, men matching._size_rank proever
# nu hvert tal i intervallet for sig via _item_size_tokens(), saa et 98/104-
# plag ogsaa kan tael som et match for et oenske om 104, ikke kun 98).
_CM_SIZE_RE = re.compile(r"CM-(\d+(?:/\d+)?)")


def _parse_cm_size(raw_size) -> str:
    """Udtraekker cm-stoerrelsen fra en Sellpy-boernestoerrelse ('CHILD-CM-80'
    -> '80', 'CHILD-CM-98/104' -> '98/104' -- se modulets docstring og G15).
    Returnerer "" for manglende/uventet format eller ikke-cm-skala (fx voksen
    'WMN-INT-S') -- crasher ALDRIG paa uventet input.
    J7-PRAECISERING: tom stoerrelse frasorterer KUN en Sellpy-voksenvare naar
    oensket selv har en numerisk stoerrelse at sammenligne med (matching._size_rank
    afviser da manglende annonce-stoerrelse). For et stoerrelsesloest oenske (G7:
    tom stoerrelse = "stoerrelse er ikke et kriterie") er der INGEN udelukkelse
    -- en voksenvare kan udmaerket matche et stoerrelsesloest oenske paa
    type+pris alene. Ingen generel "voksentoej udelukkes altid"-garanti."""
    if not raw_size:
        return ""
    m = _CM_SIZE_RE.search(str(raw_size))
    return m.group(1) if m else ""


def _algolia_search(term: str, hits_per_page: int, timeout: int) -> list[dict]:
    """Ét Algolia multi-query-kald for én soegeterm. Returnerer listen af raa
    hits (dicts) eller en tom liste ved enhver fejl."""
    import requests  # lokal import, samme moenster som playwright i de andre kilder

    body = {
        "requests": [
            {
                "indexName": ALGOLIA_INDEX,
                "params": f"query={quote(term)}&hitsPerPage={hits_per_page}",
            }
        ]
    }
    headers = {
        "x-algolia-application-id": ALGOLIA_APP_ID,
        "x-algolia-api-key": ALGOLIA_API_KEY,
        "Content-Type": "application/json",
    }
    resp = requests.post(ALGOLIA_URL, headers=headers, data=json.dumps(body), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return []
    return results[0].get("hits") or []


def _hit_to_listing(hit: dict) -> dict | None:
    """Mapper ét Algolia-hit til vores normaliserede kort-model. Returnerer None
    hvis hittet ikke er 'on shelf' (solgt/reserveret) eller mangler pris (kan da
    ikke prisfiltreres). Springer aldrig med en undtagelse -- kaldstedet fanger."""
    if not hit.get("isOnShelf"):
        return None  # solgt/reserveret -- filtreres bort (se modulets docstring)

    object_id = hit.get("objectID")
    if not object_id:
        return None

    price_dk = hit.get("price_DK") or {}
    amount_ore = price_dk.get("amount")
    if amount_ore is None:
        return None  # ingen pris -> kan ikke prisfiltrere, spring over
    try:
        price = round(float(amount_ore) / 100.0, 2)  # øre -> kroner
    except (TypeError, ValueError):
        return None

    md = hit.get("metadata") or {}
    brand = md.get("brand") or ""
    item_type = md.get("type") or ""
    # Titel bygges fra maerke+type, da matching.precheck()/_type_matches tjekker
    # oenske-typen mod annonce-TITLEN (Sellpy har intet enkelt 'titel'-felt).
    title = f"{brand} {item_type}".strip() or (object_id)

    return {
        "item_id": object_id,
        "title": title,
        "size": _parse_cm_size(md.get("size")),
        "price": price,
        "url": ITEM_URL_TMPL.format(object_id=object_id),
        "brand": brand,
        "stand": md.get("condition") or "ukendt",
        # Konsignationsmodel: konstant saelger, faelles fragt (se modulets docstring).
        "seller_name": "Sellpy",
        "seller_id": None,
        "shipping_price": None,
        "shipping_currency": "DKK",
    }


def fetch(config: dict, dry_run: bool = False) -> list[dict]:
    """Soeger Sellpy (via Algolia) for hver term i config['search_terms'] (bygget
    af monitor.py ud fra oenskesedlen, samme genbrugte termer som Reshopper/DBA)
    og returnerer raa, ALLEREDE komplette annoncer -- title/size/price/url/brand/
    stand/seller_name/seller_id/shipping_price/item_id/search_term. Alt ligger i
    Algolia-hittet, saa fetch_details() nedenfor er en no-op."""
    try:
        import requests  # noqa: F401  -- fejl tidligt+tydeligt hvis dep mangler
    except ImportError:
        logger.warning("Sellpy: 'requests' er ikke installeret, springer kilden over")
        return []

    sp_cfg = config.get("sellpy", {})
    hits_per_page = sp_cfg.get("max_results_per_term", 30)
    timeout = sp_cfg.get("timeout_s", 20)

    search_terms = config.get("search_terms") or []
    if not search_terms:
        logger.info("Sellpy: ingen soegetermer konfigureret, springer kilden over")
        return []

    raw_listings = []
    for term in search_terms:
        try:
            logger.info("Sellpy: soeger '%s' -> Algolia (%s)", term, ALGOLIA_INDEX)
            hits = _algolia_search(term, hits_per_page, timeout)
            listings = []
            for hit in hits:
                try:
                    listing = _hit_to_listing(hit)
                except Exception:
                    logger.exception("Sellpy: kunne ikke parse et hit, springer over")
                    continue
                if listing is not None:
                    listing["search_term"] = term
                    listings.append(listing)
            logger.info("Sellpy: '%s' -> %d hits (%d on-shelf m/pris)", term, len(hits), len(listings))
            raw_listings.extend(listings)
        except Exception:
            logger.exception("Sellpy: fejl under haandtering af '%s', springer over", term)
            continue

    return raw_listings


def fetch_details(
    urls: list[str], config: dict, dry_run: bool = False,
    raw_listings_by_url: dict | None = None,
) -> dict[str, dict]:
    """No-op: ALT (maerke/stand/saelger/fragt) hentes allerede i fetch()'s Algolia-
    hit, saa der er ingen separat detaljeside at besoege. Returnerer et tomt dict
    -- run_source() i monitor.py haandterer 'ingen detalje for denne url' via
    setdefault, og da fetch() allerede har sat alle felterne paa hver listing,
    aendrer den fallback intet. Beholdes for at opfylde den faelles to-fase-
    kontrakt (fetch/fetch_details) som Reshopper/DBA.
    'raw_listings_by_url' (G16-tilfoejet, uafhaengig af Sellpy) er ubrugt her."""
    return {}
