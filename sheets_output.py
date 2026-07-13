"""Google Sheets-output (dashboard). gspread + service account, samme moenster
som ejendompython-arkivets exporters/sheets_exporter.py.

VIGTIGT FUND (2026-07-08/09, bekraeftet ved direkte test mod Google-API'erne):
det genbrugte service account (ejendom-server@...) har 0 Drive-lagerkvote --
BAADE Drive-API's files.create OG Sheets-API's spreadsheets.create svarer 403
("Service Accounts do not have storage quota" / "PERMISSION_DENIED"). Dette er
en kendt, dokumenteret Google-begraensning for service accounts uden en Shared
Drive (som kraever Google Workspace, ikke en almindelig Gmail-konto) -- IKKE en
bug i denne kode. client.create() forsoeges stadig foerst (som oensket), men
fejler forudsigeligt indtil et Shared Drive er tilgaengeligt.

Praktisk konsekvens: foerste koersel kraever ét manuelt engangstrin fra Esben
(se README.md "Google Sheets-opsætning") -- akkurat samme moenster som det
EKSISTERENDE ejendompython-sheet allerede bruger (bekraeftet: det ark ejes af
esbvall@gmail.com og er blot DELT med service accountet, ikke omvendt).

Selve skrive-mekanikken (add_worksheet/update/format paa et allerede-delt ark)
ER bekraeftet at virke i praksis mod det eksisterende ejendompython-ark."""
import csv
import logging
import os
from collections import Counter
from datetime import datetime

import matching

logger = logging.getLogger("personal_shopper.sheets_output")

STATE_FILE_DEFAULT = "spreadsheet_id.txt"

# H3 (BACKLOG.md demo-kritik): stand-labels der reelt betyder "noget er galt".
# G6 (2026-07-10): generaliseret fra en fast Reshopper-specifik streng til
# matching.normalize_stand() == "defekt" -- saa DBA/Sellpy/Vinteds egne
# formuleringer af "defekt" (fx "Beskadiget", "I stykker") OGSAA flages, ikke
# kun Reshoppers ordrette "Defekt, kan laves". BAD_STAND_LABELS bevares som
# et par kendte, ordrette eksempler til reference/dokumentation, men selve
# tjekket (_is_bad_stand) bruger nu normalize_stand.
BAD_STAND_LABELS = {"Defekt, kan laves"}
STAND_WARNING_PREFIX = "⚠️ "
STAND_WARNING_BG = {"red": 0.98, "green": 0.85, "blue": 0.82}


def _is_bad_stand(stand: str) -> bool:
    """G6: True hvis stand-friteksten (fra ENHVER kilde) normaliserer til
    'defekt'-tieret (se matching.normalize_stand) -- IKKE en fast streng-
    sammenligning, saa nye/andre kilders defekt-formuleringer flages ens."""
    return matching.normalize_stand(stand) == "defekt"

# H1: MATCHES_HEADER faar en "Opslag-ID"-kolonne (kort, unik del af item-ID'et)
# saa to ens-udseende raekker fra samme saelger tydeligt kan ses som to
# FORSKELLIGE opslag uden at skulle klikke ind paa begge links (H4).
# G1 (DBA som ny kilde) tilfoejede "Kilde"-kolonnen -- naar to platforme
# vises side om side er det ikke laengere aabenlyst hvilken platform et
# opslag stammer fra, og det er ALDRIG sikkert at en saelger med samme navn
# paa to platforme er samme person (se bundling.py:_seller_key).
# G16: "Land"-kolonnen er kun udfyldt for Vinted-fund (se
# sources/vinted.py's fetch_details()) -- tom for de andre kilder.
MATCHES_HEADER = [
    "Link", "Opslag-ID", "Kilde", "Match", "Pris (kr.)", "Størrelse", "Mærke",
    "Stand", "Sælger", "Land", "Ønske (type/mærke/størrelse)", "Fragt (kr.)",
    "Først set", "Opdateret",
]

# BUNDLES_HEADER's "Opslag N"-kolonner er dynamiske (afhaenger af det
# stoerste antal items i en enkelt bundle denne koersel) -- se
# _bundles_header() nedenfor. Denne konstant bruges IKKE direkte laengere,
# men beholdes som dokumentation af de faste kolonner foer/efter link-blokken.
# G1: "Kilde" tilfoejet af samme grund som MATCHES_HEADER ovenfor.
BUNDLES_BASE_HEADER_PRE = ["Sælger", "Kilde", "Antal items", "Varer i bundle"]
BUNDLES_BASE_HEADER_POST = [
    "Samlet varepris (kr.)", "Fragt (kr.)", "Total inkl. fragt (kr.)",
    "Pris/stk i bundle (kr.)", "Pris/stk hver for sig (kr.)",
    "Besparelse/stk (kr.)", "Bundling betaler sig",
    "Lokal afhentning-bonus", "Opdateret",
]


def _bundles_header(max_items: int) -> list[str]:
    """H1: bygger Bundles-headeren dynamisk med én 'Opslag N'-kolonne pr.
    item i den stoerste bundle denne koersel -- saa hvert opslags link staar
    direkte i bundle-raekken, uden at skulle slaa op i Matches-fanen."""
    link_cols = [f"Opslag {i}" for i in range(1, max(max_items, 1) + 1)]
    return BUNDLES_BASE_HEADER_PRE + link_cols + BUNDLES_BASE_HEADER_POST


def _short_item_ref(m: dict) -> str:
    """H4: kort, synlig, unik reference til et opslag -- de sidste tegn af
    item-ID'et (Mongo-lignende hex-streng, se sources/reshopper.py) med et
    '…'-praefiks der markerer at det er en forkortelse. Bruges naar to
    matches fra samme saelger ellers ser identiske ud (samme pris/stand)."""
    ref = (m.get("item_id") or "").strip()
    if not ref:
        url = (m.get("url") or "").rstrip("/")
        ref = url.rsplit("/", 1)[-1] if url else ""
    if not ref:
        return ""
    return f"…{ref[-6:]}" if len(ref) > 6 else ref


def _or_blank(value):
    """G21-FIX: bundle-oekonomifelter (total_with_shipping m.fl.) kan nu
    vaere None (kendt udenlandsk saelger, ukendt fragt uden Vinted-login,
    se BACKLOG.md's G21/G22) -- dict.get(key, "") giver IKKE en tom
    streng her, fordi noeglen FINDES (blot med vaerdien None), saa vi maa
    tjekke eksplicit i stedet for at stole paa .get()'s default-parameter."""
    return "" if value is None else value


def _bundle_worth_it_text(b: dict) -> str:
    """G21-FIX: 'NEJ' ville fejlagtigt paastaa at bundlen BEKRAEFTET ikke
    betaler sig -- for en kendt udenlandsk saelger med ukendt fragt (kan
    sagtens vaere 2+ items) er sandheden at vi reelt IKKE VED det."""
    if b.get("shipping_dkk") is None and b.get("item_count", 0) >= 2:
        return "USIKKERT (udenlandsk sælger)"
    return "JA" if b.get("bundle_worth_it") else "NEJ"


def _display_stand(stand: str) -> str:
    """H3: praefikser en tydelig advarsel foran negative stand-labels (fx
    'Defekt, kan laves') saa de ikke fremstaar ligevaerdige med god stand i
    en hurtig visuel skim af Matches-fanen."""
    stand = stand or "ukendt"
    if _is_bad_stand(stand):
        return f"{STAND_WARNING_PREFIX}{stand}"
    return stand


def _format_kr(value, note: str = "") -> str:
    """H5: fragt vist som fx '35 kr.' i stedet for et enhedsloest tal.
    Tomt/ukendt fragt-beloeb giver fortsat en tom celle (IKKE '0 kr.' eller
    'ukendt kr.' -- vi ved reelt ikke beloebet, se sources/reshopper.py)."""
    if value is None or value == "":
        return ""
    try:
        num = float(value)
        num_str = str(int(num)) if num == int(num) else str(num)
    except (TypeError, ValueError):
        num_str = str(value)
    return f"{num_str} kr.{note}"


def _match_shipping_display(m: dict) -> str:
    """G30: viser en BEKRAEFTET fragtpris hvis kendt (uaendret adfaerd),
    ELLERS et manuelt indsamlet landegennemsnits-ESTIMAT hvis nok
    observationer findes (se bundling.apply_shipping_estimates()), ELLERS
    en tom celle -- ALDRIG et stille gaet, samme princip som _format_kr()."""
    if m.get("shipping_price") is not None:
        return _format_kr(m["shipping_price"])
    estimate = m.get("shipping_price_estimate")
    if estimate is not None:
        count = m.get("shipping_price_estimate_count") or 0
        return _format_kr(estimate, note=f" (estimat, {count} obs.)")
    return ""


def _bundle_shipping_note(b: dict) -> str:
    """G30: udvider den eksisterende '(antaget)'-note med en tredje
    tilstand -- '(estimat, N obs.)' for et landegennemsnit (se
    bundling.build_bundles()) -- adskilt fra baade en bekraeftet pris
    (ingen note) og den danske indenrigs-antagelse (fortsat '(antaget)')."""
    if b.get("shipping_is_assumed"):
        return " (antaget)"
    if b.get("shipping_is_country_estimate"):
        count = b.get("shipping_estimate_count") or 0
        return f" (estimat, {count} obs.)"
    return ""


def _items_summary(items: list[dict]) -> str:
    """H4: 'Varer i bundle'-teksten nummererer ens-udseende items (samme
    titel) inden for samme bundle -- '#1'/'#2' -- saa fx to Michelle A
    Birkholm-leggings-raekker ikke fejlagtigt ligner en duplikat-bug, men
    tydeligt er to forskellige opslag."""
    titles = [it.get("title", "") for it in items]
    counts = Counter(titles)
    seen: Counter = Counter()
    parts = []
    for it in items:
        title = it.get("title", "")
        label = title
        if counts[title] > 1:
            seen[title] += 1
            label = f"{title} #{seen[title]}"
        parts.append(f"{label} ({it.get('price', '')} kr.)")
    return "; ".join(parts)


def build_tldr_line(bundles: list[dict]) -> str:
    """H2: dynamisk "hvad betaler sig lige nu"-linje til toppen af Bundles-
    fanen/CSV'en -- genereret hver koersel ud fra de faktiske bundle-data,
    ikke hardcodet. Se BACKLOG.md's demo-kritik: travl bruger skal IKKE selv
    skulle regne ud hvilke bundles der er vaerd at handle hos."""
    worth_it_sellers = [b.get("seller_name", "ukendt") for b in bundles if b.get("bundle_worth_it")]
    if worth_it_sellers:
        return f"🟢 {len(worth_it_sellers)} bundle(s) betaler sig lige nu: {', '.join(worth_it_sellers)}"
    if bundles:
        return "🟡 Ingen bundles betaler sig endnu -- kun enkeltstaaende items pr. saelger lige nu"
    return "⚪ Ingen matches fundet endnu"


def get_sheets_client(credentials_file: str):
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ImportError("Kør: pip install gspread google-auth")

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
    return gspread.authorize(creds)


def _read_state_spreadsheet_id(state_path: str) -> str | None:
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or None
    return None


def _write_state_spreadsheet_id(state_path: str, spreadsheet_id: str) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        f.write(spreadsheet_id)


def get_or_create_spreadsheet(client, config: dict, state_path: str = STATE_FILE_DEFAULT, allow_create: bool = True):
    """Aabner det konfigurerede/tidligere-oprettede spreadsheet, eller forsoeger
    at oprette et nyt (client.create()) hvis intet ID kendes endnu.

    Raekkefoelge: 1) spreadsheet_id.txt (skrevet af en tidligere succesfuld
    auto-oprettelse i DENNE koersel-serie) 2) config.yaml's spreadsheet_id
    (manuelt saettes efter det manuelle engangstrin, se README.md)
    3) forsoeg client.create() -- forventes at fejle med denne service accounts
    0-kvote (se modulets docstring), men forsoeges alligevel som foerste
    prioritet jf. opgavebeskrivelsen. Returnerer None hvis intet lykkes.

    allow_create=False (bruges af monitor.py under --dry-run) springer
    client.create()-forsoeget helt over -- en "dry run" maa aldrig have den
    sideeffekt at oprette et rigtigt cloud-spreadsheet. Et allerede kendt
    spreadsheet (state-fil eller config) aabnes stadig read-only."""
    gs_cfg = config.get("google_sheets", {})

    state_id = _read_state_spreadsheet_id(state_path)
    if state_id:
        try:
            sh = client.open_by_key(state_id)
            logger.info("Sheets: genbruger tidligere oprettet spreadsheet (%s)", sh.url)
            return sh
        except Exception:
            logger.warning("Sheets: gemt spreadsheet_id (%s) kunne ikke aabnes, proever config/oprettelse", state_id)

    configured_id = gs_cfg.get("spreadsheet_id")
    if configured_id:
        try:
            sh = client.open_by_key(configured_id)
            logger.info("Sheets: aabnede konfigureret spreadsheet (%s)", sh.url)
            return sh
        except Exception:
            logger.exception("Sheets: kunne ikke aabne konfigureret spreadsheet_id=%s", configured_id)
            return None

    if not allow_create:
        logger.info("Sheets: intet kendt spreadsheet endnu, og --dry-run springer client.create() over")
        return None

    title = gs_cfg.get("spreadsheet_title", "Personal Shopper")
    share_email = gs_cfg.get("share_with_email")
    try:
        sh = client.create(title)
        logger.info("Sheets: nyt spreadsheet oprettet -- %s", sh.url)
        if share_email:
            sh.share(share_email, perm_type="user", role="writer")
            logger.info("Sheets: delt med %s (redigeringsadgang)", share_email)
        _write_state_spreadsheet_id(state_path, sh.id)
        return sh
    except Exception as e:
        logger.error(
            "Sheets: kunne IKKE oprette nyt spreadsheet automatisk (%s: %s). "
            "Dette er en KENDT begraensning -- service accountet har 0 Drive-"
            "lagerkvote (bekraeftet 2026-07-08/09, se modulets docstring). "
            "Manuelt engangstrin noedvendigt: se README.md 'Google Sheets-opsætning'.",
            type(e).__name__, e,
        )
        return None


def _get_or_create_worksheet(spreadsheet, name: str, rows: int = 2000, cols: int = 15):
    try:
        return spreadsheet.worksheet(name)
    except Exception:
        return spreadsheet.add_worksheet(title=name, rows=rows, cols=cols)


# ─────────────────────────────────────────────
# I1: "Kontrolpanel"-fane -- lader Esbens kone trigge en koersel NU fra selve
# Sheetet i stedet for at vente paa naeste 2x-dagligt scheduled task. Selve
# pollingen/koerslen ligger i trigger_watcher.py -- disse funktioner haandterer
# udelukkende laesning/skrivning af kontrolcellerne.
# ─────────────────────────────────────────────
CONTROL_CHECKBOX_CELL = "B2"
CONTROL_STATUS_CELL = "B3"
CONTROL_LAST_RUN_CELL = "B4"
CONTROL_STATUS_READY = "Klar"

# J3 (kritik-loop 2): "Kør nu"- og Status-raekken faar en tydelig gul-orange
# baggrund saa laenge en koersel er i gang -- teksten "Kører..." i Status-
# cellen alene er let at overse for en travl bruger. Samme moenster som H3s
# lyseroede "defekt item"-flag (STAND_WARNING_BG ovenfor), blot en anden farve
# saa de to betydninger ("advarsel" vs. "koersel i gang") ikke forveksles.
CONTROL_ROW_RANGE = "A2:D3"
CONTROL_RUNNING_BG = {"red": 1.0, "green": 0.90, "blue": 0.60}
CONTROL_NORMAL_BG = {"red": 1.0, "green": 1.0, "blue": 1.0}


def ensure_control_tab(spreadsheet, tab_name: str = "Kontrolpanel"):
    """Aabner fanen hvis den findes, ellers opretter den med en RIGTIG Sheets-
    checkbox i B2 (data-validation type BOOLEAN, ikke bare teksten "FALSE").

    gspread 6.x (installeret version bekraeftet: 6.1.2/6.2.1) har IKKE en
    insert_checkboxes()-bekvemmelighedsmetode -- saa checkboxen bygges direkte
    som en setDataValidation-request via spreadsheet.batch_update(). En tom
    condition.values-liste er noeglen: det er det der faar Sheets til at tegne
    en klikbar checkbox-widget i stedet for blot at validere fritekst mod
    TRUE/FALSE (se Sheets API-dok for BooleanCondition/DataValidationRule).

    Idempotent: hvis fanen allerede findes (fx fra en tidligere koersel)
    aabnes den blot som den er -- vi overskriver IKKE en allerede udfyldt
    Status/Sidst koert-celle ved at kalde denne funktion igen."""
    try:
        return spreadsheet.worksheet(tab_name)
    except Exception:
        pass

    ws = spreadsheet.add_worksheet(title=tab_name, rows=10, cols=4)
    ws.update([
        ["Kontrolpanel", "", "", ""],
        ["Kør nu", False,
         "Sæt hak for at køre en overvågning NU (ellers køres der automatisk 2x dagligt). "
         "Kan tage op til 15 sek. før Status skifter til 'Kører...'. Selve kørslen "
         "kan tage op til 15 min., afhængig af hvor meget nyt der skal tjekkes "
         "(J6, kritikrunde 2026-07-10: reelle kørsler har spændt fra 2,5 til 14 min.).", ""],
        ["Status", CONTROL_STATUS_READY, "", ""],
        ["Sidst kørt", "", "", ""],
    ], range_name="A1", value_input_option="USER_ENTERED")
    ws.format("A1:A4", {"textFormat": {"bold": True}})
    ws.format("A1:D1", {
        "textFormat": {"bold": True, "fontSize": 12},
        "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.98},
    })

    grid_range = {
        "sheetId": ws.id,
        "startRowIndex": 1, "endRowIndex": 2,   # raekke 2 (0-indekseret: 1)
        "startColumnIndex": 1, "endColumnIndex": 2,  # kolonne B (0-indekseret: 1)
    }
    spreadsheet.batch_update({
        "requests": [{
            "setDataValidation": {
                "range": grid_range,
                "rule": {
                    "condition": {"type": "BOOLEAN", "values": []},
                    "strict": True,
                    "showCustomUi": True,
                },
            }
        }]
    })
    ws.freeze(cols=1)
    logger.info("Sheets: fanen '%s' oprettet med 'Kør nu'-checkbox i %s", tab_name, CONTROL_CHECKBOX_CELL)
    return ws


def read_run_now(ws) -> bool:
    """Billigt polls-kald til trigger_watcher.py: laeser KUN checkbox-cellen
    (ét gspread-kald), IKKE resten af Sheetet. UNFORMATTED_VALUE giver en rigtig
    Python-bool for en checkbox-celle (i stedet for fx teksten "TRUE")."""
    value = ws.acell(CONTROL_CHECKBOX_CELL, value_render_option="UNFORMATTED_VALUE").value
    return bool(value)


def set_status(ws, text: str) -> None:
    """Saettes med det samme naar en koersel starter ('Kører...') -- ét
    lille skrive-kald, adskilt fra finish_run() saa brugeren kan se at
    koerslen er i gang mens den staar paa (kan tage op til 15 min., se
    J6/trigger_watcher.py)."""
    ws.update([[text]], range_name=CONTROL_STATUS_CELL, value_input_option="USER_ENTERED")


def lock_control_row(ws) -> None:
    """J3: taender den gul-orange 'koersel i gang'-baggrund paa 'Kør nu'- og
    Status-raekken. Kaldes af trigger_watcher.py lige efter set_status(ws,
    "Kører...") saettes ved koerselsstart -- selve checkboxen laeses/skrives
    stadig normalt (et gen-klik under en koersel er allerede ufarligt, se
    BACKLOG.md), dette er ren visuel feedback."""
    ws.format(CONTROL_ROW_RANGE, {"backgroundColor": CONTROL_RUNNING_BG})


def unlock_control_row(ws) -> None:
    """J3: modstykke til lock_control_row() -- nulstiller til normal hvid
    baggrund. Kaldes fra finish_run() saa laasen ALTID fjernes igen naar en
    koersel er faerdig, uanset om den lykkedes eller fejlede."""
    ws.format(CONTROL_ROW_RANGE, {"backgroundColor": CONTROL_NORMAL_BG})


def finish_run(ws, status_text: str, last_run_text: str) -> None:
    """Saet Status + Sidst koert + nulstil 'Kør nu'-checkboxen i ÉT batch-kald
    (i stedet for tre separate update()-kald) naar en trigget koersel er
    faerdig (succes ELLER fejl -- checkboxen skal ALTID nulstilles saa vi ikke
    trigger den samme koersel igen og igen i det uendelige). Fjerner ogsaa
    J3s "koersel i gang"-baggrund igen (samme sted i koden som saetter
    vaerdierne, saa laasen aldrig glemmes staaende)."""
    ws.batch_update([
        {"range": CONTROL_CHECKBOX_CELL, "values": [[False]]},
        {"range": CONTROL_STATUS_CELL, "values": [[status_text]]},
        {"range": CONTROL_LAST_RUN_CELL, "values": [[last_run_text]]},
    ], value_input_option="USER_ENTERED")
    unlock_control_row(ws)


def make_hyperlink(url: str, label: str = "Se annonce") -> str:
    if not url:
        return ""
    if len(url) > 1900:
        return url
    escaped = url.replace('"', "%22")
    return f'=HYPERLINK("{escaped}";"{label}")'


def write_matches(spreadsheet, matches: list[dict], first_seen_lookup: dict, now_str: str) -> int:
    """Sheet 'Matches' -- én raekke pr. match (samme annonce kan optraede
    flere gange hvis den matcher flere oenskeseddel-raekker, se matching.py)."""
    ws = _get_or_create_worksheet(spreadsheet, "Matches", cols=len(MATCHES_HEADER) + 2)
    if ws.col_count < len(MATCHES_HEADER):
        # En genbrugt fane fra foer H1-H5 kan have faerre kolonner end den nye
        # header (fx den nye "Opslag-ID") -- udvid i stedet for at fejle paa update().
        ws.resize(cols=len(MATCHES_HEADER) + 2)
    data = [MATCHES_HEADER]
    bad_stand_rows = []  # H3/G16: raekke-numre der skal have advarsels-baggrund
    for idx, m in enumerate(matches):
        wl_ref = f"{m.get('wishlist_type', '')}/{m.get('wishlist_maerke', '') or 'generisk'}/{m.get('wishlist_stoerrelse', '')}"
        first_seen = first_seen_lookup.get(m.get("_db_id"), now_str)
        stand_raw = m.get("stand", "ukendt")
        seller_country = m.get("seller_country") or ""
        # G16: samme advarsels-baggrund som defekt stand -- polske saelgere
        # er ikke udelukket (soft nedprioriteret, se matching.py), men
        # fortjener samme visuelle "se naermere efter"-advarsel.
        if _is_bad_stand(stand_raw) or seller_country in matching.DEPRIORITIZED_SELLER_COUNTRIES:
            bad_stand_rows.append(idx + 2)  # +2: header er raekke 1, data starter raekke 2
        data.append([
            make_hyperlink(m.get("url", "")),
            _short_item_ref(m),
            m.get("source", "ukendt").capitalize(),
            m.get("match_rank", ""),
            m.get("price", ""),
            m.get("size", ""),
            m.get("brand", "") or "",
            _display_stand(stand_raw),
            m.get("seller_name", "ukendt"),
            seller_country,
            wl_ref,
            _match_shipping_display(m),
            first_seen[:16] if first_seen else "",
            now_str,
        ])
    ws.clear()
    ws.update(data, range_name="A1", value_input_option="USER_ENTERED")
    last_col = chr(ord('A') + len(MATCHES_HEADER) - 1)
    ws.format(f"A1:{last_col}1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.98},
    })
    if bad_stand_rows:
        # H3: én batch-kald i stedet for ét ws.format() pr. raekke -- undgaar
        # unoedvendigt mange Sheets-API-kald naar mange items er "Defekt".
        ws.batch_format([
            {"range": f"A{r}:{last_col}{r}", "format": {"backgroundColor": STAND_WARNING_BG}}
            for r in bad_stand_rows
        ])
    ws.freeze(rows=1)
    logger.info(
        "Sheets: %d match(es) skrevet til fanen 'Matches' (%d flaget med daarlig stand)",
        len(matches), len(bad_stand_rows),
    )
    return len(matches)


def write_bundles(spreadsheet, bundles: list[dict], now_str: str) -> int:
    """Sheet 'Bundles' -- én raekke pr. saelger med mindst ét match.
    Raekke 1 er en dynamisk TL;DR (H2), raekke 2 er header, data fra raekke 3."""
    max_items = max((b.get("item_count", 1) for b in bundles), default=1)
    header = _bundles_header(max_items)
    last_col = chr(ord('A') + len(header) - 1) if len(header) <= 26 else "Z"

    ws = _get_or_create_worksheet(spreadsheet, "Bundles", cols=len(header) + 2)
    if ws.col_count < len(header):
        # Antallet af "Opslag N"-kolonner varierer koersel til koersel (afhaenger
        # af den stoerste bundle lige nu) -- udvid en genbrugt fane ved behov.
        ws.resize(cols=len(header) + 2)
    tldr_row = [build_tldr_line(bundles)] + [""] * (len(header) - 1)
    data = [tldr_row, header]
    for b in bundles:
        items = b["items"]
        # H1: én HYPERLINK-formel pr. item, direkte i bundle-raekken -- ingen
        # grund til at slaa op i Matches-fanen for at finde et opslags link.
        link_cells = [make_hyperlink(it.get("url", ""), label=f"#{i + 1}") for i, it in enumerate(items)]
        link_cells += [""] * (max_items - len(link_cells))
        data.append([
            b.get("seller_name", "ukendt"),
            b.get("source", "ukendt").capitalize(),
            b.get("item_count", 0),
            _items_summary(items),
            *link_cells,
            b.get("total_item_price", ""),
            _format_kr(b.get("shipping_dkk"), note=_bundle_shipping_note(b)),
            _or_blank(b.get("total_with_shipping")),
            _or_blank(b.get("effective_price_per_item")),
            _or_blank(b.get("alone_price_per_item")),
            _or_blank(b.get("savings_per_item")),
            _bundle_worth_it_text(b),  # H5: konsekvent case
            "JA" if b.get("local_pickup_bonus") else "NEJ",
            now_str,
        ])
    ws.clear()
    try:
        # En tidligere koersel kan have mergede A1:<en anden bredde>1 -- ws.clear()
        # fjerner kun VAERDIER, ikke merges/formatering, saa vi unmerger foerst for
        # at undgaa en API-fejl hvis dette antal kolonner er aendret.
        ws.unmerge_cells("A1:Z1")
    except Exception:
        pass
    ws.update(data, range_name="A1", value_input_option="USER_ENTERED")
    ws.merge_cells(f"A1:{last_col}1")
    ws.format(f"A1:{last_col}1", {
        "textFormat": {"bold": True, "fontSize": 11},
        "backgroundColor": {"red": 0.90, "green": 0.96, "blue": 0.90},
        "horizontalAlignment": "LEFT",
    })
    ws.format(f"A2:{last_col}2", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.98, "green": 0.95, "blue": 0.85},
    })
    ws.freeze(rows=2)
    logger.info("Sheets: %d bundle(s) skrevet til fanen 'Bundles' (TL;DR: %s)", len(bundles), tldr_row[0])
    return len(bundles)


def write_local_csv_fallback(matches: list[dict], bundles: list[dict], first_seen_lookup: dict | None = None, out_dir: str = ".") -> None:
    """Bruges KUN naar Google Sheets ikke er tilgaengeligt (se
    get_or_create_spreadsheet) -- saa resultaterne stadig er synlige et sted i
    stedet for at forsvinde helt. IKKE et krav fra briefen, men undgaar at en
    koersel foeles "tabt" foer det manuelle Sheets-engangstrin er paa plads."""
    first_seen_lookup = first_seen_lookup or {}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    matches_path = os.path.join(out_dir, "matches_fallback.csv")
    with open(matches_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(MATCHES_HEADER)
        for m in matches:
            wl_ref = f"{m.get('wishlist_type', '')}/{m.get('wishlist_maerke', '') or 'generisk'}/{m.get('wishlist_stoerrelse', '')}"
            first_seen = first_seen_lookup.get(m.get("_db_id"), "")
            writer.writerow([
                m.get("url", ""), _short_item_ref(m), m.get("source", "ukendt").capitalize(),
                m.get("match_rank", ""), m.get("price", ""),
                m.get("size", ""), m.get("brand", "") or "", _display_stand(m.get("stand", "ukendt")),
                m.get("seller_name", "ukendt"), wl_ref,
                _match_shipping_display(m), first_seen[:16] if first_seen else "", now_str,
            ])
    bundles_path = os.path.join(out_dir, "bundles_fallback.csv")
    max_items = max((b.get("item_count", 1) for b in bundles), default=1)
    header = _bundles_header(max_items)
    with open(bundles_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([build_tldr_line(bundles)])  # H2: TL;DR-linje foerst i CSV'en ogsaa
        writer.writerow(header)
        for b in bundles:
            items = b["items"]
            # H1: raa URL'er pr. item (CSV understoetter ikke HYPERLINK-formler) --
            # stadig direkte klik-/kopiérbare uden at slaa op i matches_fallback.csv.
            link_cells = [it.get("url", "") for it in items]
            link_cells += [""] * (max_items - len(link_cells))
            writer.writerow([
                b.get("seller_name", "ukendt"), b.get("source", "ukendt").capitalize(),
                b.get("item_count", 0), _items_summary(items),
                *link_cells,
                b.get("total_item_price", ""),
                _format_kr(b.get("shipping_dkk"), note=_bundle_shipping_note(b)),
                _or_blank(b.get("total_with_shipping")), _or_blank(b.get("effective_price_per_item")),
                _or_blank(b.get("alone_price_per_item")), _or_blank(b.get("savings_per_item")),
                _bundle_worth_it_text(b),
                "JA" if b.get("local_pickup_bonus") else "NEJ",
                now_str,
            ])
    logger.warning(
        "Sheets utilgaengeligt -- skrev lokal fallback i stedet: %s, %s. "
        "Faerdiggoer det manuelle Sheets-engangstrin (README.md) for rigtigt dashboard-output.",
        matches_path, bundles_path,
    )
