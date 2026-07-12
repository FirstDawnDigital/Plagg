"""Reshopper.com: Next.js-SPA bag Vercel bot-management, robots.txt Disallow: /.

F1-spike (BACKLOG.md, 2026-07-08/09) bekraeftede:
  - Almindelig curl/HTTP-klient bliver 429'et med header 'x-vercel-mitigated:
    challenge'. En RIGTIG Playwright Chromium-browser (headless=True virker
    fint) henter forsiden med status 200 -- INGEN offentligt API fundet.
  - Modsat hvad F1 antog, viste et efterfoelgende interaktivt tjek 2026-07-09
    at '?q=<term>'-URL-moenstret RENT FAKTISK filtrerer resultater server-/
    client-side (bekraeftet: 'leggings' -> 40.269 varer, 'birkholm' -> 2.256,
    et opdigtet noeglerord -> 0). Vi navigerer derfor direkte til denne URL i
    stedet for at simulere klik i soegefeltet -- simplere og mere robust.
  - Soegeresultatsiden viser kun ~10 kort ved foerste load i headless-test
    (ingen bekraeftet infinite-scroll/"vis flere"-trigger) -- kendt
    begraensning, se BACKLOG.md.
  - Annoncedetalje-siden ('/item/<slug>/<id>') indeholder et STANDARD
    schema.org 'application/ld+json'-Product-blok (SEO-markup) med pris,
    saelgernavn, fragtpris (shippingDetails.shippingRate) og grov stand
    (itemCondition). Dette er langt mere robust end at parse Tailwind-klasser,
    som skifter jaevnligt i Next.js-builds. Praecis dansk stand-label (fx
    "God, men brugt") findes IKKE i JSON-LD, men som en synlig pille i DOM'en
    -- hentes med tekst-match mod den kendte facet-ordliste, IKKE en CSS-klasse
    (klassenavne er obfuskerede Tailwind-utility-klasser der kan aendre sig).
  - En stabil saelger-ID (Mongo ObjectId) findes IKKE i noget href (ingen
    "Se shop"-link har en <a href>), men KAN udtraekkes best-effort fra en
    indlejret React-Server-Component JSON-streng i <script>-tags, ankret til
    det praecise item-ID fra URL'en (for at undgaa fejlagtigt at hive en
    saelger-ID fra "Lignende varer"-sektionen nederst paa siden).

Fejler ALDRIG hele scriptet: bot-wall eller andre problemer logges og giver
blot en tom liste for denne koersel (se personal-shopper-brief.md §7 og
BACKLOG.md's F1-fund om robots.txt/graazone-tilgang).
"""
import json
import logging
import random
import re
import time
from urllib.parse import quote

from scraper_core.pricing import parse_price

logger = logging.getLogger("personal_shopper.reshopper")

# HAERDNINGS-NOTE (2026-07-10, se hang_guard.py's docstring): Playwrights
# close()-metoder har INGEN timeout-parameter (bekraeftet mod installeret
# playwright==1.61.0 -- kun et 'reason'-keyword). Vi proevede en traad-baseret
# timeout-wrapper omkring context.close()/browser.close() nedenfor, men
# test_hang_diagnostics.py afsloerede at det AKTIVT OEDELAEGGER Playwrights
# sync-API (greenlet.error: cannot switch to a different thread) -- Playwrights
# SyncBase._sync() bruger et greenlet bundet til det OS-traad der oprindeligt
# aabnede sync_playwright(), og close() SKAL derfor kaldes fra den SAMME
# traad. Den reelle beskyttelse mod et haengende close()-kald er derfor
# monitor.py's globale proces-watchdog (hang_guard.install_hard_watchdog) --
# den rammer intet Playwright-objekt direkte, kun OS-primitiver
# (threading.Timer + os.killpg/os._exit), saa den ER sikker at koere fra en
# anden traad.

BASE_URL = "https://reshopper.com"
SEARCH_URL_TMPL = BASE_URL + "/da?q={query}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Danske tekstmarkoerer som FALLBACK-signal -- primaersignalet er 429-status/
# 'x-vercel-mitigated'-headeren (se _looks_like_bot_wall), da Reshopper er bag
# Vercel bot-management og ikke en klassisk tekst-CAPTCHA-side som Kleinanzeigen.
BOT_WALL_TEXT_MARKERS = [
    "bekræft at du er et menneske",
    "unormal trafik",
    "adgang nægtet",
    "captcha",
    "access denied",
]

# Reshoppers egne danske stand-labels (bekraeftet i facet-sidebaren og paa
# item-detaljesiden 2026-07-09) -- bruges til tekst-match i DOM'en, IKKE en
# CSS-selector, saa parsingen overlever Tailwind-klasse-churn.
KNOWN_STAND_LABELS = ["Helt ny", "Næsten som ny", "God, men brugt", "Defekt, kan laves"]

# Grov fallback hvis den praecise danske label ikke kan findes i DOM'en, men
# JSON-LD's 'itemCondition' stadig er tilgaengelig.
CONDITION_MAP = {
    "NewCondition": "Helt ny",
    "UsedCondition": "brugt (ukendt grad)",
    "DamagedCondition": "Defekt, kan laves",
    "RefurbishedCondition": "Istandsat",
}

# Linje-moenstre i et annoncekorts rene inner_text() -- robust mod Tailwind-
# klasse-churn, se _parse_search_cards.
_AGE_SIZE_RE = re.compile(r"^\s*(\d+)\s*(år|mdr|md)\s*/\s*(.+?)\s*$", re.IGNORECASE)
_PRICE_RE = re.compile(r"^\s*([\d.,]+)\s*kr\.?\s*$", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"/item/[^/]+/([0-9a-f]+)$")


def _build_search_url(term: str) -> str:
    return SEARCH_URL_TMPL.format(query=quote(term))


def _dismiss_cookie_overlay(page) -> None:
    """Sourcepoint-cookie-consent-overlayet (id starter med 'sp_message_container')
    blokerer klik paa resten af siden. Vi klikker den ikke -- vi fjerner den
    direkte fra DOM'en, da vi kun laeser tekst/attributter og ikke skal klikke
    andre elementer igennem den."""
    try:
        page.evaluate(
            "() => document.querySelectorAll('[id^=sp_message_container]').forEach(e => e.remove())"
        )
    except Exception:
        pass  # ikke kritisk -- vi klikker ikke gennem overlayet alligevel


def _looks_like_bot_wall(response, page) -> bool:
    """Primaersignal: HTTP 429 + Vercels 'x-vercel-mitigated: challenge'-header.
    Fallback: danske tekstmarkoerer i sidens indhold (se BACKLOG.md F1-fund)."""
    if response is not None:
        try:
            if response.status == 429:
                return True
            if (response.headers.get("x-vercel-mitigated") or "").lower() == "challenge":
                return True
        except Exception:
            pass
    try:
        content = page.content().lower()
        return any(marker in content for marker in BOT_WALL_TEXT_MARKERS)
    except Exception:
        return False


def _parse_search_cards(page, limit: int) -> list[dict]:
    """Selectors/struktur bekraeftet mod reelt Reshopper-markup 2026-07-09:
    hvert annoncekort er en <a href="/item/<slug>/<id>"> hvis rene inner_text()
    er linjebaseret ('Plus'?, titel, '<alder> år|mdr / <størrelse>', '<pris> kr.',
    favorit-antal). Vi parser linjerne med regex i stedet for CSS-klasser, da
    Tailwind-utility-klasserne er lange, obfuskerede og aendrer sig ved redeploys."""
    anchors = page.query_selector_all('a[href*="/item/"]')
    results = []
    for a in anchors[:limit]:
        try:
            href = a.get_attribute("href")
            if not href:
                continue
            id_match = _ITEM_ID_RE.search(href)
            item_id = id_match.group(1) if id_match else href

            lines = [l.strip() for l in (a.inner_text() or "").split("\n") if l.strip()]
            lines = [l for l in lines if l.lower() != "plus"]  # "Plus"-medlemsbadge, ikke del af titlen
            if not lines:
                continue
            title = lines[0]

            size = None
            price = None
            for line in lines[1:]:
                if size is None:
                    m = _AGE_SIZE_RE.match(line)
                    if m:
                        size = m.group(3).strip()
                        continue
                if price is None:
                    m = _PRICE_RE.match(line.replace("\xa0", " "))
                    if m:
                        # G29: scraper_core.pricing.parse_price(), unit=
                        # "major" (allerede kr., ikke oere). decimal_style
                        # TVUNGET til "comma" (IKKE "auto") -- Reshoppers
                        # priser er ALTID dansk-formaterede (punktum =
                        # tusind-separator, komma = decimal), ALDRIG
                        # tvetydige med engelsk konvention. VIGTIGT FUND
                        # (2026-07-13): "auto" fejlfortolker en pris UDEN
                        # komma overhovedet (fx "1.234" for "1234 kr.",
                        # et helt tusind uden oere) som punktum-decimal
                        # (1.234, ~1000x for lavt!) -- "auto" er designet
                        # til at haandtere tvetydige/blandede kilder, men
                        # her ER der ingen tvetydighed at haandtere.
                        price = parse_price(m.group(1), unit="major", decimal_style="comma")

            if price is None:
                continue  # kan ikke prisfiltrere uden en pris -- spring over

            url = BASE_URL + href if href.startswith("/") else href
            results.append({
                "item_id": item_id,
                "title": title,
                "size": size or "ukendt",
                "price": price,
                "url": url,
            })
        except Exception:
            logger.exception("Reshopper: kunne ikke parse et annoncekort, springer over")
    return results


def fetch(config: dict, dry_run: bool = False) -> list[dict]:
    """Soeger Reshopper for hver term i config['search_terms'] (bygget af
    monitor.py ud fra oenskesedlens type+mærke-kombinationer) og returnerer
    raa kort-niveau-annoncer: item_id/title/size/price/url/search_term.

    Stand, saelger og fragt kraever et besoeg paa annoncens egen side -- det
    goer fetch_details() nedenfor, kaldt af monitor.py KUN for kandidater der
    allerede har bestaaet det foerste (kort-niveau) match/pris-filter, saa vi
    ikke poller flere sider end noedvendigt (skaansomt mod Reshopper, jf.
    robots.txt Disallow: / og Esbens eksplicitte oenske om lav kadence)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Reshopper: playwright er ikke installeret, springer kilden over")
        return []

    pw_cfg = config.get("playwright", {})
    headless = pw_cfg.get("headless", True)
    min_delay = pw_cfg.get("min_delay_s", 5)
    max_delay = pw_cfg.get("max_delay_s", 15)
    max_results_per_term = pw_cfg.get("max_results_per_term", 10)

    search_terms = config.get("search_terms") or []
    if not search_terms:
        logger.info("Reshopper: ingen soegetermer konfigureret, springer kilden over")
        return []

    raw_listings = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="da-DK",
            )
            page = context.new_page()

            for term in search_terms:
                try:
                    url = _build_search_url(term)
                    logger.info("Reshopper: soeger '%s' -> %s", term, url)
                    response = page.goto(url, timeout=25000)
                    page.wait_for_timeout(1500)  # lad client-side rendering faerdiggoere
                    _dismiss_cookie_overlay(page)

                    if _looks_like_bot_wall(response, page):
                        logger.warning(
                            "Reshopper: bot-wall/challenge moedt for '%s' (status=%s), "
                            "springer kilden over for RESTEN af denne koersel",
                            term, response.status if response else "?",
                        )
                        break  # stop heldt -- ingen aggressiv retry, jf. Esbens graazone-aftale

                    cards = _parse_search_cards(page, max_results_per_term)
                    logger.info("Reshopper: '%s' -> %d kort", term, len(cards))
                    for card in cards:
                        card["search_term"] = term
                        raw_listings.append(card)

                    time.sleep(random.uniform(min_delay, max_delay))
                except Exception:
                    logger.exception("Reshopper: fejl under haandtering af '%s', springer over", term)
                    continue

            # BEMAERK (haerdnings-forsoeg 2026-07-10): proevede oprindeligt at
            # wrappe disse close()-kald i en baggrunds-traad + join(timeout)
            # (se hang_guard.safe_close) for at give dem en timeout, siden
            # Playwrights close()-metoder ikke selv tager et timeout-argument
            # (bekraeftet mod installeret playwright==1.61.0 -- kun 'reason').
            # Test (test_hang_diagnostics.py) afsloerede at dette AKTIVT
            # OEDELAEGGER Playwrights sync-API: SyncBase._sync() bruger et
            # greenlet bundet til det OS-traad der oprindeligt kaldte
            # sync_playwright(), og et close()-kald fra en ANDEN traad fejler
            # med 'greenlet.error: cannot switch to a different thread'.
            # Playwrights sync-API er med andre ord IKKE traadsikker paa
            # denne maade -- close() SKAL kaldes fra samme traad som resten af
            # denne funktion. Den reelle beskyttelse mod et haengende close()-
            # kald er derfor monitor.py's GLOBALE proces-watchdog
            # (hang_guard.install_hard_watchdog) -- den rammer intet
            # Playwright-objekt direkte (kun OS-primitiver: threading.Timer +
            # os.killpg/os._exit), saa den ER sikker at koere fra en anden
            # traad.
            context.close()
            browser.close()
    except Exception:
        logger.exception("Reshopper: kilden fejlede helt, springer kilden over for denne koersel")
        return []

    return raw_listings


def _extract_json_ld_product(page) -> dict | None:
    """Finder Product-blokken blandt siden's application/ld+json-scripts
    (standard schema.org SEO-markup -- bekraeftet stabilt og langt mindre
    skroebeligt end at parse Tailwind-DOM'en)."""
    try:
        scripts = page.query_selector_all('script[type="application/ld+json"]')
        for script in scripts:
            try:
                data = json.loads(script.inner_text())
            except Exception:
                continue
            if isinstance(data, dict) and data.get("@type") == "Product":
                return data
    except Exception:
        pass
    return None


def _extract_seller_id(html: str, item_id: str) -> str | None:
    """Best-effort udtraek af Reshoppers interne saelger-ID (Mongo ObjectId) fra
    en indlejret React-Server-Component JSON-streng. Ankret til DETTE items
    praecise ID (fra URL'en) for at undgaa fejlagtigt at hive en saelger-ID fra
    "Lignende varer"-sektionen nederst paa siden, som ogsaa indeholder
    item->userId-par for andre annoncer. Ikke en officiel/dokumenteret struktur
    -- kan knaekkes ved et Reshopper-redeploy, deraf try/except + fallback til
    saelgernavn i normalize.py."""
    try:
        pattern = r'\\"id\\":\\"' + re.escape(item_id) + r'\\",\\"userId\\":\\"([0-9a-f]{24})\\"'
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _find_stand_label(page) -> str | None:
    """Scanner DOM'en for et element hvis tekst er PRAECIS en af Reshoppers
    kendte danske stand-labels (se KNOWN_STAND_LABELS) -- tekst-match, ikke en
    CSS-klasse, saa den overlever Tailwind-klasse-churn."""
    try:
        js = """(labels) => {
            const els = document.querySelectorAll('*');
            for (const el of els) {
                if (el.children.length === 0) {
                    const t = el.textContent.trim();
                    if (labels.includes(t)) return t;
                }
            }
            return null;
        }"""
        return page.evaluate(js, KNOWN_STAND_LABELS)
    except Exception:
        return None


def fetch_details(
    urls: list[str], config: dict, dry_run: bool = False,
    raw_listings_by_url: dict | None = None,
) -> dict[str, dict]:
    """Besoeger hver annonce-URL for stand/saelger/fragt -- kaldes af monitor.py
    KUN for allerede kort-niveau-filtrerede kandidater (se fetch()-docstring).
    Returnerer {url: {brand, stand, seller_name, seller_id, shipping_price,
    shipping_currency, condition_raw}}. En enkelt annonces fejl paavirker aldrig
    de andre -- manglende detaljer giver blot "ukendt"-felter for den annonce.
    'raw_listings_by_url' (G16-tilfoejet for Vinted) er ubrugt her -- Reshopper
    henter alt fra selve detaljesiden, ikke fra det raa soegekort."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Reshopper: playwright er ikke installeret, springer detalje-opslag over")
        return {}

    pw_cfg = config.get("playwright", {})
    headless = pw_cfg.get("headless", True)
    min_delay = pw_cfg.get("min_delay_s", 5)
    max_delay = pw_cfg.get("max_delay_s", 15)

    details = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            for url in urls:
                # Frisk context pr. annonce (samme forsigtighedsprincip som
                # Kleinanzeigen-kildens session-degraderings-fund, se db.py-arkivet)
                context = browser.new_context(user_agent=USER_AGENT, locale="da-DK")
                page = context.new_page()
                try:
                    logger.info("Reshopper: henter detaljer -> %s", url)
                    response = page.goto(url, timeout=25000)
                    page.wait_for_timeout(1200)
                    _dismiss_cookie_overlay(page)

                    if _looks_like_bot_wall(response, page):
                        logger.warning(
                            "Reshopper: bot-wall/challenge moedt under detalje-opslag, "
                            "springer RESTEN af detalje-opslagene over for denne koersel"
                        )
                        # context.close() sker i finally-blokken nedenfor --
                        # kaldte den ogsaa her tidligere, hvilket betoed et
                        # (harmloest, men unoedvendigt) dobbelt close()-kald
                        # for netop denne bot-wall-vej.
                        break

                    id_match = _ITEM_ID_RE.search(url)
                    item_id = id_match.group(1) if id_match else None

                    product = _extract_json_ld_product(page)
                    stand_label = _find_stand_label(page)

                    detail = {
                        "brand": None,
                        "condition_raw": None,
                        "stand": stand_label or "ukendt",
                        "seller_name": "ukendt",
                        "seller_id": None,
                        "shipping_price": None,
                        "shipping_currency": "DKK",
                    }
                    if product:
                        brand = product.get("brand") or {}
                        detail["brand"] = brand.get("name")
                        offers = product.get("offers") or {}
                        seller = offers.get("seller") or {}
                        detail["seller_name"] = seller.get("name") or "ukendt"
                        shipping = (offers.get("shippingDetails") or {}).get("shippingRate") or {}
                        detail["shipping_price"] = shipping.get("value")
                        detail["shipping_currency"] = shipping.get("currency", "DKK")
                        condition_url = product.get("itemCondition") or ""
                        condition_raw = condition_url.rsplit("/", 1)[-1] if condition_url else None
                        detail["condition_raw"] = condition_raw
                        if detail["stand"] == "ukendt" and condition_raw:
                            detail["stand"] = CONDITION_MAP.get(condition_raw, "ukendt")

                    if item_id:
                        html = page.content()
                        seller_id = _extract_seller_id(html, item_id)
                        detail["seller_id"] = seller_id

                    details[url] = detail
                    time.sleep(random.uniform(min_delay, max_delay))
                except Exception:
                    logger.exception("Reshopper: fejl under detalje-opslag for %s, springer over", url)
                finally:
                    # Se fetch()'s tilsvarende kommentar ovenfor: en traad-
                    # baseret timeout-wrapper omkring close() blev testet og
                    # forkastet (oedelaegger Playwrights sync-API paa tvaers
                    # af traade) -- monitor.py's globale watchdog er den
                    # reelle beskyttelse mod et haengende close()-kald her.
                    context.close()

            browser.close()
    except Exception:
        logger.exception("Reshopper: detalje-opslag fejlede helt, resten af koerslen fortsaetter uden detaljer")

    return details
