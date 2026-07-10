"""DBA.dk: Schibsted/Vend-markedsplads bygget som en Podium-mikrofrontend
(webkomponenter med SHADOW DOM -- fx <finn-topbar>, <recommerce-suggestions-
podlet-isolated>). G1-spike (BACKLOG.md, 2026-07-09) bekraeftede:

  - Login er LAAST for anonyme klienter (saelgernavn/-profil kraever en
    logget-ind session). Esben oprettede en DEDIKERET DBA-konto
    (firstdawndigital@gmail.com), loggede ind MANUELT (Google reCAPTCHA paa
    selve login-siden -- IKKE noget der forsoeges omgaaet automatiseret her)
    og eksporterede cookies til '.dba_storage_state.json' (Playwright
    storage_state-format, IKKE i git). Denne kilde laeser UDELUKKENDE den
    fil -- forsoeger ALDRIG selv at logge ind eller forny sessionen. Hvis
    filen mangler eller sessionen viser sig udloebet, stopper vi og logger
    det tydeligt (se _session_looks_logged_in nedenfor) i stedet for at
    omgaa det.
  - robots.txt er permissiv (kun /my-page, /messages, /favorites, /profile*,
    /map* disallowed for User-Agent *) -- lavere risiko end Reshopper, men
    samme skaansomme kadence (5-15s delays) alligevel, jf. Esbens graazone-
    aftale for hele projektet.
  - URL-moenstre: soegning
    'https://www.dba.dk/recommerce/forsale/search?q=<term>', annonceside
    'https://www.dba.dk/recommerce/forsale/item/<id>' (ren numerisk ID,
    IKKE '/item/<slug>/<id>' som Reshopper).
  - VIGTIGT DOM-fund: soegeresultat-kortenes <a>-taggs ligger i almindelig
    light DOM (native document.querySelectorAll finder dem fint), MEN
    saelgersektionen paa annoncesiden (navn, MitID, "Kontakt saelger") er
    renderet inde i et Podium-webkomponent-SHADOW-ROOT -- hverken
    page.content() eller document.body.innerText/textContent naar ind i et
    shadow-root, saa begge gav UVENTET TOMT resultat i flere forsoeg (se
    BACKLOG.md's G1-fund). Kun Playwrights EGNE locator/query_selector-kald
    (som piercer shadow-DOM som standard) eller en JS-evaluate der eksplicit
    traverserer element.shadowRoot naar ind til den.
  - FUNDET, BEDRE END DOM-scanning: annoncesiden indeholder et <script>-tag
    (inde i et shadow-root) med 'window.__staticRouterHydrationData =
    JSON.parse("...")' -- en server-renderet JSON-blob med ALT vi behoever:
    saelgernavn (profileData.profile.identity.name), en STABIL numerisk
    saelger-ID (itemData.meta.ownerId -- langt mere paalidelig end
    Reshoppers best-effort regex-udtraek), fragttekst ("Fragt fra 29,99 kr.
    + ...") og en praecis dansk stand-label via extras-listen (id="condition",
    label="Stand") -- mere praecis end JSON-LD's grove itemCondition-enum.
    Denne JSON er SERVER-renderet (til stede allerede ved domcontentloaded,
    ikke afhaengig af klient-hydrering saa taet som DOM-tekst-scanning), men
    er stadig en UOFFICIEL/udokumenteret intern struktur -- kan braekke ved
    et DBA/Vend-redeploy. Fejler den, falder vi tilbage til JSON-LD (samme
    schema.org-Product-blok som Reshopper bruger) for pris/maerke/stand, og
    saelgernavn/-ID bliver "ukendt"/None for netop den annonce.

Fejler ALDRIG hele scriptet: bot-wall, manglende/udloebet session eller
andre problemer logges og giver blot en tom liste for denne koersel."""
import json
import logging
import os
import random
import re
import time
from urllib.parse import quote

logger = logging.getLogger("personal_shopper.dba")

# HAERDNINGS-NOTE (2026-07-10) -- se sources/reshopper.py's identiske note og
# hang_guard.py's docstring: en traad-baseret timeout-wrapper omkring
# context.close()/browser.close() blev proevet og forkastet (test_hang_
# diagnostics.py afsloerede at det oedelaegger Playwrights sync-API paa tvaers
# af traade -- 'greenlet.error: cannot switch to a different thread'). Den
# reelle beskyttelse mod et haengende close()-kald her er monitor.py's
# globale proces-watchdog (hang_guard.install_hard_watchdog), som IKKE
# roerer noget Playwright-objekt direkte.

BASE_URL = "https://www.dba.dk"
SEARCH_URL_TMPL = BASE_URL + "/recommerce/forsale/search?q={query}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Fallback-signal hvis vi alligevel skulle moede en bot-wall-side (robots.txt
# er permissiv, saa ikke observeret i praksis under G1-spiken, men samme
# forsigtighedsprincip som sources/reshopper.py -- fejl skal ALDRIG antages
# ved en tavs, tom liste uden logning).
#
# BEMAERK: "captcha" er BEVIDST IKKE med her (modsat reshopper.py) -- DBA
# indlejrer Googles reCAPTCHA-JS/iframe paa helt almindelige annoncesider
# (formentlig til kontakt-saelger-formularen), saa ordet gav et falsk
# positivt bot-wall-signal paa en normal, 200-OK annonceside under test
# 2026-07-09. De resterende markoerer er specifikke danske spaerre-
# sidefraser, ikke observeret paa almindelige sider.
BOT_WALL_TEXT_MARKERS = [
    "bekræft at du er et menneske",
    "unormal trafik",
    "adgang nægtet",
    "for mange forespørgsler",
]

# Samme grov-mapping som sources/reshopper.py's CONDITION_MAP -- bruges KUN
# som fallback naar hydration-JSON'ens praecise "Stand"-extra (se
# _extract_hydration_data) ikke kunne udtraekkes. "DamagedCondition" mapper
# bevidst til PRAECIS samme tekst som sheets_output.py's BAD_STAND_LABELS
# forventer, saa H3-advarselsflaget ogsaa virker for DBA-fund.
CONDITION_MAP = {
    "NewCondition": "Helt ny",
    "UsedCondition": "Brugt (ukendt grad)",
    "DamagedCondition": "Defekt, kan laves",
    "RefurbishedCondition": "Istandsat",
}

_ITEM_ID_RE = re.compile(r"/item/(\d+)")
_PRICE_LINE_RE = re.compile(r"^([\d.,]+)\s*kr\.?$", re.IGNORECASE)
_SIZE_RE = re.compile(r"Str\.\s*(\S+)", re.IGNORECASE)
_KR_AMOUNT_RE = re.compile(r"([\d.,]+)\s*kr\.", re.IGNORECASE)

# Ankrer regex'en til den praecise 'window.__staticRouterHydrationData =
# JSON.parse("...")'-tildeling -- se modulets docstring. Greedy '.*' op til
# SIDSTE '"' foer ');' virker fordi hele tildelingen staar paa én linje uden
# et matchende ');' midt i JSON-strengen.
_HYDRATION_RE = re.compile(r'window\.__staticRouterHydrationData = JSON\.parse\((".*")\);')

# JS der finder <script>-tags MED hydration-markoeren paa tvaers af ALLE
# shadow-roots (native querySelectorAll piercer IKKE shadow-DOM, saa vi maa
# traversere element.shadowRoot manuelt -- se modulets docstring).
_JS_FIND_HYDRATION_SCRIPTS = """
() => {
    function walk(root, results) {
        const scripts = root.querySelectorAll('script');
        for (const s of scripts) {
            if (s.textContent && s.textContent.includes('staticRouterHydrationData')) {
                results.push(s.textContent);
            }
        }
        const all = root.querySelectorAll('*');
        for (const el of all) {
            if (el.shadowRoot) walk(el.shadowRoot, results);
        }
    }
    const results = [];
    walk(document, results);
    return results;
}
"""

# JS der finder soegeresultat-kortene. Kortenes <a href="/recommerce/forsale/
# item/<id>">-taggs ligger i almindelig light DOM (bekraeftet 2026-07-09), men
# et enkelt opslag har FLERE <a>-tags (billede, titel, "Gaa til annoncen"-
# knap) der alle peger paa samme href -- vi dedupliker paa item-ID og finder
# selve kort-containeren ved at gaa op til naermeste forfader hvis inner_text
# indeholder 'kr.' (robust mod Tailwind/CSS-klasse-churn, samme princip som
# sources/reshopper.py's regex-baserede kort-parsing).
_JS_FIND_SEARCH_CARDS = """
(limit) => {
    const anchors = Array.from(document.querySelectorAll('a[href*="/recommerce/forsale/item/"]'));
    const seen = new Set();
    const out = [];
    for (const a of anchors) {
        const href = a.getAttribute('href');
        const m = href && href.match(/\\/item\\/(\\d+)/);
        if (!m) continue;
        const id = m[1];
        if (seen.has(id)) continue;
        seen.add(id);
        let el = a;
        let card = null;
        for (let i = 0; i < 8 && el; i++) {
            el = el.parentElement;
            if (!el) break;
            const txt = el.innerText || "";
            if (txt.includes("kr.")) { card = el; break; }
        }
        out.push({
            id: id,
            href: href.startsWith("http") ? href : (location.origin + href),
            cardText: card ? card.innerText : "",
        });
        seen.add(id);
        if (out.length >= limit) break;
    }
    return out;
}
"""


def _build_search_url(term: str) -> str:
    return SEARCH_URL_TMPL.format(query=quote(term))


def _parse_kr_amount(text: str) -> float | None:
    """Udtraekker det foerste 'X kr.'-beloeb i en tekststreng (dansk
    talformat, komma som decimal) -- bruges baade til kort-priser og til
    fragt-teksten ('Fragt fra 29,99 kr. + Tryg betaling 11 kr.')."""
    if not text:
        return None
    m = _KR_AMOUNT_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _looks_like_bot_wall(response, page) -> bool:
    """Samme to-lags signal som sources/reshopper.py: HTTP 403/429 som
    primaersignal, danske tekstmarkoerer i page.content() (ren light-DOM-
    HTML, IKKE afhaengig af shadow-DOM-traversering) som fallback."""
    if response is not None:
        try:
            if response.status in (403, 429):
                return True
        except Exception:
            pass
    try:
        content = page.content().lower()
        return any(marker in content for marker in BOT_WALL_TEXT_MARKERS)
    except Exception:
        return False


def _session_looks_logged_in(page) -> bool:
    """Tjekker for login-only-navigation ('Min DBA'/'Beskeder'-links til
    /my-page og /messages i topbaren) -- BEKRAEFTET at disse links ligger
    inde i <finn-topbar>'s shadow-root, saa vi bruger Playwrights EGEN
    locator (som piercer shadow-DOM som standard), IKKE page.content() eller
    document.querySelectorAll (native DOM-API'er ser IKKE ind i et
    shadow-root -- bekraeftet gav 0 traeff i test selvom en logget-ind
    session rent faktisk viste linkene visuelt, se BACKLOG.md's G1-fund).

    Returnerer False hvis sessionen ser udloebet/ugyldig ud -- IKKE et
    signal om at proeve at logge ind selv (det skal eskaleres til Esben,
    se modulets docstring og BACKLOG.md)."""
    try:
        return page.locator('a[href*="/my-page"], a[href*="/messages"]').count() > 0
    except Exception:
        return False


def _parse_search_cards(cards: list[dict]) -> list[dict]:
    """Parser de raa {id, href, cardText}-dicts fra _JS_FIND_SEARCH_CARDS til
    vores normaliserede kort-model. Prisen staar altid foerst i kortets
    inner_text, titlen lige efter -- stoerrelse (evt. slet ikke angivet)
    udtraekkes med et separat regex-soeg der virker uanset raekkefoelge
    laengere nede (nogle kategorier viser maerke FOER 'Str. X', andre
    EFTER -- se G1-fund)."""
    results = []
    for card in cards:
        try:
            text = card.get("cardText") or ""
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            price = None
            price_idx = None
            for i, line in enumerate(lines):
                m = _PRICE_LINE_RE.match(line.replace("\xa0", " "))
                if m:
                    try:
                        price = float(m.group(1).replace(".", "").replace(",", "."))
                    except ValueError:
                        price = None
                    price_idx = i
                    break
            if price is None:
                continue  # ingen fast pris (fx "Byttes") -- kan ikke prisfiltrere, spring over

            title = lines[price_idx + 1] if price_idx + 1 < len(lines) else ""
            size_m = _SIZE_RE.search(text)
            size = size_m.group(1) if size_m else "ukendt"

            results.append({
                "item_id": card["id"],
                "title": title,
                "size": size,
                "price": price,
                "url": card["href"],
            })
        except Exception:
            logger.exception("DBA: kunne ikke parse et annoncekort, springer over")
    return results


def fetch(config: dict, dry_run: bool = False) -> list[dict]:
    """Soeger DBA for hver term i config['search_terms'] (bygget af
    monitor.py, samme genbrugte wishlist-baserede termer som Reshopper) og
    returnerer raa kort-niveau-annoncer: item_id/title/size/price/url/
    search_term. Stand/saelger/fragt kraever et besoeg paa annoncens egen
    side -- det goer fetch_details() nedenfor, kaldt af monitor.py KUN for
    kandidater der allerede har bestaaet foerste (kort-niveau) match/pris-
    filter (matching.precheck())."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("DBA: playwright er ikke installeret, springer kilden over")
        return []

    dba_cfg = config.get("dba", {})
    storage_state_file = dba_cfg.get("storage_state_file", ".dba_storage_state.json")
    if not os.path.exists(storage_state_file):
        logger.warning(
            "DBA: storage_state-fil '%s' findes ikke -- login-session mangler. "
            "Springer DBA-kilden HELT over for denne koersel (se BACKLOG.md's "
            "G1-fund for hvordan filen genskabes -- IKKE noget der skal loeses "
            "automatisk her).",
            storage_state_file,
        )
        return []

    headless = dba_cfg.get("headless", True)
    min_delay = dba_cfg.get("min_delay_s", 5)
    max_delay = dba_cfg.get("max_delay_s", 15)
    max_results_per_term = dba_cfg.get("max_results_per_term", 10)

    search_terms = config.get("search_terms") or []
    if not search_terms:
        logger.info("DBA: ingen soegetermer konfigureret, springer kilden over")
        return []

    raw_listings = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                storage_state=storage_state_file,
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="da-DK",
            )
            page = context.new_page()

            session_checked = False
            for term in search_terms:
                try:
                    url = _build_search_url(term)
                    logger.info("DBA: soeger '%s' -> %s", term, url)
                    response = page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2500)  # lad client-side rendering faerdiggoere

                    if _looks_like_bot_wall(response, page):
                        logger.warning(
                            "DBA: bot-wall/challenge moedt for '%s' (status=%s), "
                            "springer kilden over for RESTEN af denne koersel",
                            term, response.status if response else "?",
                        )
                        break

                    if not session_checked:
                        # Kun noedvendigt at tjekke én gang pr. koersel -- samme
                        # context/cookies genbruges for alle soegetermer.
                        if not _session_looks_logged_in(page):
                            logger.error(
                                "DBA: login-session ser UDLOEBET/UGYLDIG ud (ingen "
                                "login-only-navigation fundet i topbaren). STOPPER "
                                "DBA-kilden helt -- dette skal ESKALERES TIL ESBEN "
                                "(manuel login + Cookie-Editor-eksport, se "
                                "BACKLOG.md's G1-fund), IKKE forsoeges omgaaet her."
                            )
                            break
                        session_checked = True

                    cards = _parse_search_cards(page.evaluate(_JS_FIND_SEARCH_CARDS, max_results_per_term))
                    logger.info("DBA: '%s' -> %d kort", term, len(cards))
                    for card in cards:
                        card["search_term"] = term
                        raw_listings.append(card)

                    time.sleep(random.uniform(min_delay, max_delay))
                except Exception:
                    logger.exception("DBA: fejl under haandtering af '%s', springer over", term)
                    continue

            context.close()
            browser.close()
    except Exception:
        logger.exception("DBA: kilden fejlede helt, springer kilden over for denne koersel")
        return []

    return raw_listings


def _extract_json_ld_product(page) -> dict | None:
    """Samme fremgangsmaade som sources/reshopper.py: standard schema.org
    'application/ld+json'-Product-blok, bekraeftet ogsaa til stede paa DBA's
    annonceside (ligger i light DOM, IKKE i et shadow-root, saa almindelig
    query_selector_all finder den uden problemer)."""
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


def _extract_hydration_data(page) -> dict | None:
    """Udtraekker DBA's interne 'window.__staticRouterHydrationData'-JSON-
    blob (se modulets docstring) -- giver saelgernavn, en STABIL numerisk
    saelger-ID, fragttekst og en praecis dansk stand-label. Scriptet ligger
    inde i et shadow-root, saa vi maa bruge en JS-evaluate der traverserer
    element.shadowRoot manuelt (_JS_FIND_HYDRATION_SCRIPTS) i stedet for
    Playwrights normale query_selector_all (som ganske vist piercer
    shadow-DOM for CSS-selectors, men vi har brug for at IDENTIFICERE
    scriptet ved dets tekstindhold foerst).

    Uofficiel/udokumenteret struktur -- kan braekke ved et DBA/Vend-redeploy.
    Returnerer None ved enhver fejl, saa kaldestedet kan falde tilbage til
    JSON-LD alene."""
    try:
        scripts = page.evaluate(_JS_FIND_HYDRATION_SCRIPTS)
    except Exception:
        return None
    for script_text in scripts:
        try:
            m = _HYDRATION_RE.search(script_text)
            if not m:
                continue
            inner_json_str = json.loads(m.group(1))  # afkoder JS-string-literal-escaping
            data = json.loads(inner_json_str)         # den egentlige JSON-struktur
            return data["loaderData"]["item-recommerce"]
        except Exception:
            continue
    return None


def fetch_details(urls: list[str], config: dict, dry_run: bool = False) -> dict[str, dict]:
    """Besoeger hver annonce-URL for stand/saelger/fragt -- kaldes af
    monitor.py KUN for allerede kort-niveau-filtrerede kandidater (se
    fetch()-docstring). Returnerer {url: {brand, stand, seller_name,
    seller_id, shipping_price, shipping_currency, condition_raw}}. En enkelt
    annonces fejl paavirker aldrig de andre -- manglende detaljer giver blot
    "ukendt"-felter for den annonce."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("DBA: playwright er ikke installeret, springer detalje-opslag over")
        return {}

    dba_cfg = config.get("dba", {})
    storage_state_file = dba_cfg.get("storage_state_file", ".dba_storage_state.json")
    if not os.path.exists(storage_state_file):
        logger.warning("DBA: storage_state-fil '%s' findes ikke, springer detalje-opslag over", storage_state_file)
        return {}

    headless = dba_cfg.get("headless", True)
    min_delay = dba_cfg.get("min_delay_s", 5)
    max_delay = dba_cfg.get("max_delay_s", 15)

    details = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            session_checked = False
            for url in urls:
                # Frisk context pr. annonce (samme forsigtighedsprincip som
                # sources/reshopper.py), men genindlaeser samme storage_state
                # hver gang -- vi forsoeger ALDRIG at forny/omgaa sessionen.
                context = browser.new_context(
                    storage_state=storage_state_file, user_agent=USER_AGENT, locale="da-DK",
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()
                try:
                    logger.info("DBA: henter detaljer -> %s", url)
                    response = page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)

                    if _looks_like_bot_wall(response, page):
                        logger.warning(
                            "DBA: bot-wall/challenge moedt under detalje-opslag, "
                            "springer RESTEN af detalje-opslagene over for denne koersel"
                        )
                        # context.close() sker i finally-blokken nedenfor --
                        # de eksplicitte close()-kald her (og ved udloebet
                        # session lige nedenfor) blev tidligere kaldt IGEN,
                        # et (harmloest, men unoedvendigt) dobbelt close().
                        break

                    if not session_checked:
                        if not _session_looks_logged_in(page):
                            logger.error(
                                "DBA: login-session ser UDLOEBET/UGYLDIG ud under "
                                "detalje-opslag. STOPPER -- eskalér til Esben (se "
                                "BACKLOG.md's G1-fund), forsoeger IKKE at logge ind."
                            )
                            break
                        session_checked = True

                    product = _extract_json_ld_product(page)
                    hydration = _extract_hydration_data(page)

                    detail = {
                        "brand": None,
                        "condition_raw": None,
                        "stand": "ukendt",
                        "seller_name": "ukendt",
                        "seller_id": None,
                        "shipping_price": None,
                        "shipping_currency": "DKK",
                    }

                    if product:
                        brand_raw = product.get("brand")
                        detail["brand"] = brand_raw.get("name") if isinstance(brand_raw, dict) else brand_raw
                        condition_url = product.get("itemCondition") or ""
                        condition_raw = condition_url.rsplit("/", 1)[-1] if condition_url else None
                        detail["condition_raw"] = condition_raw
                        if condition_raw:
                            detail["stand"] = CONDITION_MAP.get(condition_raw, "ukendt")

                    if hydration:
                        try:
                            item_data = hydration.get("itemData") or {}
                            profile = ((hydration.get("profileData") or {}).get("profile") or {})
                            identity = profile.get("identity") or {}
                            if identity.get("name"):
                                detail["seller_name"] = identity["name"]
                            owner_id = (item_data.get("meta") or {}).get("ownerId")
                            if owner_id is not None:
                                detail["seller_id"] = str(owner_id)

                            # Praecis dansk stand-tekst fra extras -- foretraekkes
                            # over JSON-LD's grove itemCondition-enum naar den findes.
                            for extra in item_data.get("extras") or []:
                                if extra.get("id") == "condition" and extra.get("value"):
                                    detail["stand"] = extra["value"]
                                    break

                            shipping_text = (
                                (hydration.get("transactableUiData") or {})
                                .get("sections", {}).get("sidebar", {})
                                .get("optedIn", {}).get("shippingPrice", {}).get("text")
                            )
                            shipping_amount = _parse_kr_amount(shipping_text)
                            if shipping_amount is not None:
                                detail["shipping_price"] = shipping_amount
                        except Exception:
                            logger.exception(
                                "DBA: hydration-JSON fundet men uventet struktur for %s "
                                "-- bruger kun JSON-LD-felterne for denne annonce", url,
                            )

                    details[url] = detail
                    time.sleep(random.uniform(min_delay, max_delay))
                except Exception:
                    logger.exception("DBA: fejl under detalje-opslag for %s, springer over", url)
                finally:
                    context.close()

            browser.close()
    except Exception:
        logger.exception("DBA: detalje-opslag fejlede helt, resten af koerslen fortsaetter uden detaljer")

    return details
