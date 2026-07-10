"""Vinted.dk (G9): ny match-kilde via anonym cookie-priming + ét offentligt
catalog-API-kald pr. soegeterm. Samme genre af udfordring som Sellpy (intet
login noedvendigt), men Vinted sidder bag DataDome, saa vi bruger en aeldre-
skole HTTP-cookie-jar-tilgang i stedet for Sellpys helt cookie-loese Algolia-kald.

G9-spike (BACKLOG.md, 2026-07-10) RE-VERIFICERET med rigtige kald 2026-07-10
(spikens fund holdt, ingen aendringer fundet):
  - Ingen login noedvendigt. Vi primer en cookie-jar med
    'GET https://www.vinted.dk/' (almindelig browser-UA) -- saetter
    'anon_id'+'access_token_web'+flere session-cookies. UDEN disse cookies
    giver /api/v2/catalog/items et 401 MED JSON-body ("invalid_authentication_
    token") -- IKKE en DataDome-HTML-challenge-side, men samme praktiske
    konsekvens (kilden kan ikke bruges), saa vi behandler det ens (se
    _looks_like_bot_wall).
  - Soegning: 'GET https://www.vinted.dk/api/v2/catalog/items?search_text=
    <term>&per_page=<N>&page=1' MED de primede cookies + samme UA -> ren
    JSON. robots.txt (hentet MED browser-UA -- uden UA-header gav en
    generisk 403 der intet har med DataDome at goere) bekraefter Allow: /
    for User-agent: *, kun /checkout,/util,/apipie/,/admin_alert/new,
    /member/,/inbox er disallowed -- /catalog og /api/v2 er tilladt. Samme
    fil disallower dog eksplicit navngivne AI-bots (GPTBot/ClaudeBot/osv.)
    for hele sitet -- vi identificerer os IKKE som saadan (almindelig
    Chrome-UA, samme princip som Reshopper/DBA), men graazonen er den
    samme som Esben allerede har godkendt for de kilder.
  - BEKRAEFTEDE feltstier i hvert catalog-hit (verificeret mod query
    "Molo leggings", "Name it flyverdragt", "H&M body", "Joha uld
    undertøj", "Polarn O. Pyret jakke", "Birkholm leggings" 2026-07-10):
      id                  -> item-ID (int)
      title               -> Vinted har (modsat Sellpy) ALLEREDE en faerdig
                             titel pr. hit (fx "Molo tights storlek 152"),
                             saa vi bruger den direkte -- intet behov for at
                             bygge en selv af maerke+type.
      price.amount        -> pris i DKK (streng, fx "47.26") -- dette er
                             SAELGERS pris, FOER Vinteds koeberbeskyttelses-
                             gebyr. VALGT som vores 'price'-felt (se
                             _hit_to_listing for begrundelse).
      service_fee.amount  -> koeberbeskyttelses-gebyr, laegges OVENPÅ
                             price.amount. IKKE brugt til matching.
      total_item_price.amount -> price.amount + service_fee.amount = det
                             samlede beloeb koeberen reelt betaler. IKKE
                             valgt som 'price' (se begrundelse nedenfor).
      brand_title         -> maerke (fx "Molo", "H&M")
      size_title           -> STOR VARIATION, bekraeftet 4 distinkte former:
                             1) BOERNETOEJ (det vi soeger): "<alder> / <cm>
                                cm", fx "5 år / 110 cm", "18-24 måneder /
                                86 cm", "12 år / 152 cm" -- vi udtraekker
                                CM-TALLET (ikke alderen) med regex, da det
                                er den vaerdi der ligger paa
                                matching.SIZE_LADDER.
                             2) Voksen/bogstav-stoerrelser: "S / 36 / 8",
                                "M / 38 / 10" -- INGEN "cm" i strengen,
                                giver "" (tom stoerrelse), samme princip
                                som sources/sellpy.py's ikke-cm-skalaer.
                             3) "Én størrelse" (one-size) -> "" (tom).
                             4) Helt tomt felt "" (set for enkelte hits,
                                aarsag ukendt) -> "" (tom).
      status              -> dansk stand-tekst (fx "Meget god", "God", "Ny
                             med prismærker") -- allerede paa dansk, ingen
                             oversaettelse noedvendig (modsat Reshoppers
                             CONDITION_MAP-fallback).
      user.id/user.login/user.profile_url -> RIGTIG individuel saelger
                             (Vinted er IKKE konsignation som Sellpy) --
                             seller_id/seller_name saettes herfra, vigtigt
                             for bundling.py (Vinted er bevidst IKKE i
                             bundling.NON_BUNDLEABLE_SOURCES, se der).
      url                 -> fuld annonce-URL, allerede til stede paa
                             hit-niveau (modsat Sellpy skal vi ikke selv
                             bygge den af et objectID-template).
      is_visible          -> observeret 'true' paa alle hits i test; vi
                             filtrerer defensivt hvis den skulle vaere
                             eksplicit false (samme forsigtighed som
                             Sellpys isOnShelf-tjek), men behandler
                             manglende felt som synlig (ikke observeret at
                             mangle i praksis).

  PRISVALG (vigtigt, laes foer du aendrer): vi bruger price.amount, IKKE
  total_item_price.amount. Begrundelse: (1) opgavens instruktion beder
  eksplicit om "den REELLE varepris, ikke inkl. gebyrer" -- price.amount ER
  varens pris foer Vinteds koeberbeskyttelsesgebyr laegges til; (2) det
  holder priser sammenlignelige paa tvaers af kilder (Reshopper/DBA har
  ingen tilsvarende obligatorisk koeberbeskyttelses-gebyr paa selve
  vareprisen, saa at inkludere total_item_price ville systematisk goere
  Vinted-fund se dyrere ud end de facto sammenlignelige fund andre steder).
  matching.py's maks_pris-filter sammenligner derfor mod den "rene" pris,
  ikke det endelige koebs-beloeb.

  FRAGT UNDERSOEGT, IKKE TILGAENGELIG ANONYMT (vigtig aerlig konklusion):
  hverken catalog-hittet eller item-detaljesiden indeholder en fragtpris
  naar man IKKE er logget ind. Konkret afproevet 2026-07-10:
    - Intet fragt-/shipping-felt paa catalog-hit-niveau overhovedet.
    - Item-detaljesidens 'application/ld+json'-Product-blok (samme
      schema.org-tilgang som Reshopper/DBA bruger til fragt) findes godt
      nok, men mangler 'offers.shippingDetails' helt -- kun navn/maerke/
      pris/stand.
    - 'GET https://www.vinted.dk/api/v2/items/<id>' (det interne API der
      formentlig indeholder fragt-info til den indloggede frontend) giver
      404 UDEN en gyldig login-session -- ikke et parse-problem, item
      findes tydeligvis (samme ID virker fint i catalog-soegningen), saa
      det er en bevidst adgangsbegraensning, ikke en midlertidig fejl.
  Konklusion: fragt kan IKKE hentes uden login (uden for denne opgaves
  scope) -- shipping_price saettes derfor til None for alle Vinted-fund,
  ligesom Sellpys faelles/no-data-tilfaelde, men af en anden grund
  (manglende adgang, ikke en faelles/konstant fragtpris).

  G16 (2026-07-10): fetch_details() er IKKE laengere en no-op. Live-
  bekraeftet: 'GET /api/v2/users/<saelger-id>' svarer 200 MED JSON ANONYMT
  (modsat /api/v2/items/<id> ovenfor, som kraever login) og indeholder
  'country_code' direkte (fx "DK"/"PL"/"SE", verificeret paa 12 rigtige
  saelgere paa tvaers af 5 soegetermer 2026-07-10) -- INTET behov for at
  scrape profilside-HTML (den oprindeligt planlagte, mere skroebele
  tilgang). fetch_details() slaar nu hver kandidats saelgers land op (ét
  kald pr. UNIK saelger, se dens docstring) og tilfoejer 'seller_country' --
  brand/stand/seller_name/shipping_price forbliver uaendret fra fetch().

Vinted-saelgere er RIGTIGE individuelle personer (modsat Sellpys
konsignationsmodel) -- Vinted er derfor IKKE i bundling.NON_BUNDLEABLE_
SOURCES, og bundler normalt pr. saelger ligesom Reshopper/DBA.

Fejler ALDRIG hele scriptet: netvaerks-/parsefejl/bot-wall logges og giver
blot en tom liste (eller springer det enkelte hit over), aldrig en
undtagelse op i monitor.py."""
import logging
import random
import re
import time
from urllib.parse import quote

logger = logging.getLogger("personal_shopper.vinted")

BASE_URL = "https://www.vinted.dk/"
SEARCH_URL_TMPL = "https://www.vinted.dk/api/v2/catalog/items?search_text={query}&per_page={per_page}&page=1"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# G14: et par alternative browser-UA'er til priming-retries. Et enkelt
# transient 403 paa forsiden (observeret i praksis -- Esbens rapport om at
# Vinted-resultater manglede helt i en koersel) skal ikke nulstille HELE
# kildens resultat for koerslen; vi proever et par gange med stigende
# ventetid FOER vi giver op, og roterer UA mellem forsoeg i tilfaelde af at
# DataDome flagger den foerste UA specifikt.
_PRIMING_USER_AGENTS = [
    USER_AGENT,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

_PRIMING_MAX_ATTEMPTS = 3

# Danske/engelske tekstmarkoerer som FALLBACK-signal for en DataDome-
# challenge-side -- primaersignalet er 403/429-status ELLER at et JSON-kald
# uventet faar et HTML-svar tilbage (se _looks_like_bot_wall). Vinted er en
# international side, saa vi tjekker begge sprog (modsat Reshopper/DBA der
# kun har brug for danske markoerer).
BOT_WALL_TEXT_MARKERS = [
    "bekræft at du er et menneske",
    "unormal trafik",
    "adgang nægtet",
    "for mange forespørgsler",
    "captcha",
    "access denied",
    "datadome",
    "are you a robot",
    "human verification",
]

# Foerste cm-tal i en boernetoejs-stoerrelse ("5 år / 110 cm" -> "110",
# "18-24 måneder / 86 cm" -> "86"). Se modulets docstring for de tre andre
# observerede size_title-former, som ALLE bevidst giver "" her (ingen match).
_CM_SIZE_RE = re.compile(r"(\d+)\s*cm\b", re.IGNORECASE)


def _build_search_url(term: str, per_page: int) -> str:
    return SEARCH_URL_TMPL.format(query=quote(term), per_page=per_page)


def _parse_cm_size(size_title) -> str:
    """Udtraekker cm-tallet fra en Vinted-boernestoerrelse ('5 år / 110 cm'
    -> '110'). Returnerer "" for voksen-/bogstav-stoerrelser ('S / 36 / 8'),
    'Én størrelse', eller et helt tomt felt -- crasher ALDRIG paa uventet
    input. Tom stoerrelse behandles af matching._size_rank som "stoerrelse
    er ikke et kriterie" for stoerrelsesloese oensker (G7), og udelukker KUN
    et oenske der selv har en numerisk stoerrelse -- samme princip som
    sources/sellpy.py's _parse_cm_size."""
    if not size_title:
        return ""
    m = _CM_SIZE_RE.search(str(size_title))
    return m.group(1) if m else ""


def _is_json_response(resp) -> bool:
    ctype = (resp.headers.get("content-type") or "").lower()
    return "json" in ctype


def _looks_like_bot_wall(resp) -> bool:
    """Tre-lags signal: (1) HTTP 403/429 (klassisk DataDome-blokering) eller
    401 (observeret naar cookie-jar'en mangler/er ugyldig -- 'invalid_
    authentication_token', praktisk samme konsekvens som en bot-wall: kilden
    kan ikke bruges denne gang); (2) et JSON-kald der uventet faar et
    HTML-svar (DataDome serverer typisk en HTML-challenge-side selv med
    status 200); (3) danske/engelske tekstmarkoerer som fallback hvis
    content-type alligevel siger 'json' men kroppen ikke kan parses."""
    try:
        if resp.status_code in (401, 403, 429):
            return True
    except Exception:
        pass
    if not _is_json_response(resp):
        return True
    try:
        return any(marker in resp.text.lower() for marker in BOT_WALL_TEXT_MARKERS)
    except Exception:
        return False


def _prime_session(timeout: int, max_attempts: int = _PRIMING_MAX_ATTEMPTS):
    """Henter forsiden med en almindelig browser-UA for at saette en anonym
    cookie-jar (anon_id + access_token_web m.fl.) -- se modulets docstring.
    Returnerer en requests.Session med cookies sat, eller None hvis ALLE
    forsoeg fejlede (netvaerksfejl eller uventet status/bot-wall).

    G14: proever op til `max_attempts` gange med stigende ventetid (2-5s,
    4-10s, ...) og roterende UA (_PRIMING_USER_AGENTS) FOER kilden opgives --
    et enkelt transient 403/429 paa forsiden skal ikke stille hele Vinted-
    kilden i skammekrogen for en hel koersel."""
    import requests

    for attempt in range(max_attempts):
        session = requests.Session()
        session.headers.update({
            "User-Agent": _PRIMING_USER_AGENTS[attempt % len(_PRIMING_USER_AGENTS)],
            "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        })
        try:
            resp = session.get(BASE_URL, timeout=timeout)
        except Exception:
            logger.exception(
                "Vinted: netvaerksfejl under cookie-priming (forsoeg %d/%d)",
                attempt + 1, max_attempts,
            )
            resp = None

        if resp is not None and resp.status_code == 200 and session.cookies.get("anon_id"):
            if attempt > 0:
                logger.info(
                    "Vinted: cookie-priming lykkedes efter %d forsoeg", attempt + 1,
                )
            return session

        if resp is not None:
            if resp.status_code != 200:
                logger.warning(
                    "Vinted: cookie-priming fik uventet status %s fra forsiden "
                    "(forsoeg %d/%d)",
                    resp.status_code, attempt + 1, max_attempts,
                )
            else:
                logger.warning(
                    "Vinted: cookie-priming gav status 200 men ingen 'anon_id'-"
                    "cookie (forsoeg %d/%d) -- Vinted kan have aendret sit "
                    "cookie-skema",
                    attempt + 1, max_attempts,
                )

        if attempt < max_attempts - 1:
            backoff_s = random.uniform(2, 5) * (attempt + 1)
            time.sleep(backoff_s)

    logger.warning(
        "Vinted: cookie-priming fejlede efter %d forsoeg, springer kilden over "
        "for denne koersel",
        max_attempts,
    )
    return None


def _hit_to_listing(hit: dict) -> dict | None:
    """Mapper ét catalog-hit til vores normaliserede kort-model. Returnerer
    None hvis hittet mangler pris (kan da ikke prisfiltreres) eller
    eksplicit er markeret usynligt. Springer aldrig med en undtagelse --
    kaldstedet fanger."""
    if hit.get("is_visible") is False:
        return None  # eksplicit skjult/afsluttet -- filtreres bort

    item_id = hit.get("id")
    if item_id is None:
        return None
    item_id = str(item_id)

    price_obj = hit.get("price") or {}
    amount_raw = price_obj.get("amount")
    if amount_raw is None:
        return None  # ingen pris (fx byttes-annonce) -- kan ikke prisfiltrere
    try:
        price = round(float(amount_raw), 2)  # se modulets docstring for prisvalg-begrundelse
    except (TypeError, ValueError):
        return None

    url = hit.get("url")
    if not url:
        return None  # intet link -- ubrugelig annonce, spring over

    user = hit.get("user") or {}
    seller_id = user.get("id")

    return {
        "item_id": item_id,
        "title": hit.get("title") or "",
        "size": _parse_cm_size(hit.get("size_title")),
        "price": price,
        "url": url,
        "brand": hit.get("brand_title") or "",
        "stand": hit.get("status") or "ukendt",
        "seller_name": user.get("login") or "ukendt",
        "seller_id": str(seller_id) if seller_id is not None else None,
        # Ikke tilgaengelig anonymt -- se modulets docstring ("FRAGT
        # UNDERSOEGT, IKKE TILGAENGELIG ANONYMT").
        "shipping_price": None,
        "shipping_currency": price_obj.get("currency_code") or "DKK",
    }


def fetch(config: dict, dry_run: bool = False) -> list[dict]:
    """Soeger Vinted for hver term i config['search_terms'] (bygget af
    monitor.py ud fra oenskesedlen, samme genbrugte termer som Reshopper/
    DBA/Sellpy) og returnerer raa, ALLEREDE komplette annoncer -- title/
    size/price/url/brand/stand/seller_name/seller_id/shipping_price/item_id/
    search_term. Alt (undtagen fragt, se modulets docstring) ligger i
    catalog-hittet, saa fetch_details() nedenfor er en bevidst no-op."""
    try:
        import requests  # noqa: F401 -- fejl tidligt+tydeligt hvis dep mangler
    except ImportError:
        logger.warning("Vinted: 'requests' er ikke installeret, springer kilden over")
        return []

    vt_cfg = config.get("vinted", {})
    per_page = vt_cfg.get("max_results_per_term", 20)
    timeout = vt_cfg.get("timeout_s", 20)
    min_delay = vt_cfg.get("min_delay_s", 5)
    max_delay = vt_cfg.get("max_delay_s", 15)

    search_terms = config.get("search_terms") or []
    if not search_terms:
        logger.info("Vinted: ingen soegetermer konfigureret, springer kilden over")
        return []

    raw_listings = []
    try:
        session = _prime_session(timeout)
        if session is None:
            return []  # allerede logget i _prime_session

        for term in search_terms:
            try:
                url = _build_search_url(term, per_page)
                logger.info("Vinted: soeger '%s' -> catalog/items", term)
                resp = session.get(url, timeout=timeout, headers={"Accept": "application/json"})

                if _looks_like_bot_wall(resp):
                    logger.warning(
                        "Vinted: bot-wall/challenge (eller ugyldig session) moedt for '%s' "
                        "(status=%s), springer kilden over for RESTEN af denne koersel",
                        term, resp.status_code,
                    )
                    break

                if resp.status_code != 200:
                    logger.warning(
                        "Vinted: uventet status %s for '%s', springer denne term over",
                        resp.status_code, term,
                    )
                    continue

                data = resp.json()
                hits = data.get("items") or []
                listings = []
                for hit in hits:
                    try:
                        listing = _hit_to_listing(hit)
                    except Exception:
                        logger.exception("Vinted: kunne ikke parse et hit, springer over")
                        continue
                    if listing is not None:
                        listing["search_term"] = term
                        listings.append(listing)
                logger.info("Vinted: '%s' -> %d hits (%d m/pris)", term, len(hits), len(listings))
                raw_listings.extend(listings)

                time.sleep(random.uniform(min_delay, max_delay))
            except Exception:
                logger.exception("Vinted: fejl under haandtering af '%s', springer over", term)
                continue
    except Exception:
        logger.exception("Vinted: kilden fejlede helt, springer kilden over for denne koersel")
        return []

    return raw_listings


USER_API_URL_TMPL = "https://www.vinted.dk/api/v2/users/{user_id}"


def _fetch_seller_country(session, seller_id: str, timeout: int) -> tuple[str | None, bool]:
    """G16-fund (2026-07-10, live bekraeftet): Vinteds bruger-API
    ('GET /api/v2/users/<id>') svarer 200 MED JSON ANONYMT (modsat
    '/api/v2/items/<id>' som 404'er uden login, se modulets docstring om
    fragt) og indeholder 'country_code' (fx 'DK'/'PL'/'SE') direkte -- INTET
    behov for at scrape profilside-HTML, langt mere robust. Returnerer
    (landekode-eller-None, hit_bot_wall). hit_bot_wall=True signalerer til
    kaldstedet at stoppe RESTEN af land-opslagene for denne koersel (samme
    kredsloebsafbryder-princip som fetch()'s bot-wall-haandtering)."""
    try:
        resp = session.get(
            USER_API_URL_TMPL.format(user_id=seller_id), timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except Exception:
        logger.exception("Vinted: netvaerksfejl ved land-opslag for saelger %s", seller_id)
        return None, False
    if _looks_like_bot_wall(resp):
        logger.warning(
            "Vinted: bot-wall/challenge moedt ved land-opslag for saelger %s", seller_id,
        )
        return None, True
    if resp.status_code != 200:
        logger.warning(
            "Vinted: uventet status %s ved land-opslag for saelger %s",
            resp.status_code, seller_id,
        )
        return None, False
    try:
        return (resp.json().get("user") or {}).get("country_code") or None, False
    except Exception:
        logger.exception("Vinted: kunne ikke parse land-opslags-svar for saelger %s", seller_id)
        return None, False


def fetch_details(
    urls: list[str], config: dict, dry_run: bool = False,
    raw_listings_by_url: dict | None = None,
) -> dict[str, dict]:
    """G16: IKKE laengere en no-op. brand/stand/seller_name/shipping_price
    kommer FORTSAT fra fetch()'s catalog-hit (uaendret, se modulets
    docstring) -- denne funktion tilfoejer KUN 'seller_country' (Esbens
    oenske om at se/nedprioritere efter land, se BACKLOG.md's G16).

    ÉT opslag PR. UNIK SAELGER, ikke pr. annonce -- flere annoncer fra samme
    saelger (almindeligt) genbruger opslaget inden for samme koersel, saa vi
    ikke spilder kald paa allerede kendt data. Kraever 'raw_listings_by_url'
    (leveret af monitor.py's run_source(), se dens G16-kommentar) for at
    kunne slaa saelger-ID op pr. URL -- uden den (fx et kald udefra uden
    denne kwarg) returneres blot et tomt dict, ingen undtagelse.

    Stopper RESTEN af land-opslagene for koerslen ved foerste bot-wall
    (samme kredsloebsafbryder-princip som fetch()) -- allerede opslaaede
    saelgere i denne koersel beholder deres fund, resten faar blot ingen
    'seller_country' (matching/visning behandler manglende land som
    ukendt, ikke som en fejl)."""
    if not raw_listings_by_url:
        logger.warning(
            "Vinted: fetch_details() kaldt uden raw_listings_by_url, "
            "kan ikke slaa saelger-land op -- springer over"
        )
        return {}

    try:
        import requests  # noqa: F401 -- fejl tidligt+tydeligt hvis dep mangler
    except ImportError:
        logger.warning("Vinted: 'requests' er ikke installeret, springer land-opslag over")
        return {}

    vt_cfg = config.get("vinted", {})
    timeout = vt_cfg.get("timeout_s", 20)
    min_delay = vt_cfg.get("min_delay_s", 5)
    max_delay = vt_cfg.get("max_delay_s", 15)

    session = _prime_session(timeout)
    if session is None:
        return {}  # allerede logget i _prime_session

    country_by_seller: dict[str, str | None] = {}
    details: dict[str, dict] = {}
    for url in urls:
        listing = raw_listings_by_url.get(url) or {}
        seller_id = listing.get("seller_id")
        if not seller_id:
            continue  # intet saelger-id at slaa land op paa

        if seller_id not in country_by_seller:
            logger.info("Vinted: slaar land op -> saelger %s", seller_id)
            country, hit_bot_wall = _fetch_seller_country(session, seller_id, timeout)
            if hit_bot_wall:
                logger.warning(
                    "Vinted: land-opslag stoppet for RESTEN af denne koersel (bot-wall)"
                )
                break
            country_by_seller[seller_id] = country
            time.sleep(random.uniform(min_delay, max_delay))

        details[url] = {"seller_country": country_by_seller[seller_id]}

    logger.info(
        "Vinted: land-opslag faerdig -- %d unik(ke) saelger(e) slaaet op, %d annonce(r) beriget",
        len(country_by_seller), len(details),
    )
    return details
