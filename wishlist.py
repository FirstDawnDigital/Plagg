"""Ønskeseddel-indlæsning: TRE mulige kilder, valgt via config['wishlist']['source']:
'sheet' (Google Sheet-fane), 'local' (YAML-fallback, test/uden Sheets-adgang)
eller 'turso' (den hostede webapp/database). Se personal-shopper-brief.md §4.

VIGTIGT (G8, 2026-07-10): 'turso' er den AKTIVE kilde i produktion (se
config.yaml's wishlist.source) -- Esben og hans kone redigerer ønskesedlen i
webappen (https://firstdawndigital.github.io/Plagg/), IKKE laengere i Google
Sheetets "Ønskeseddel"-fane. Den fane laeses derfor ALDRIG af load_wishlist()
saa laenge source=turso -- se J4 i BACKLOG.md's kritikrunde 2026-07-10 og
advarslen skrevet direkte ind i selve Sheet-fanen (sheets_output.py-lignende
gspread-kald, koert som et engangs-script).

Sheet-fanen (naar 'sheet' rent faktisk bruges) forventes at have kolonner
svarende til COLUMN_ALIASES nedenfor -- raekkefoelge er ligegyldig,
kolonnenavne matches case-insensitivt saa Esbens kone kan skrive "Mærke"
eller "Brand" uden at det knaekker noget.
"""
import logging

import yaml

import turso_io

logger = logging.getLogger("personal_shopper.wishlist")

# Kendte spalte-navne pr. internt felt -- foerste match i raekken vinder.
COLUMN_ALIASES = {
    "type": ["type"],
    "maerke": ["mærke", "maerke", "brand"],
    "stoerrelse": ["størrelse", "stoerrelse", "size"],
    "maks_pris": ["maks-pris", "maks_pris", "makspris", "max_price", "maks pris"],
    "stand": ["stand", "kvalitet", "condition"],
}


def _normalize_row(row: dict) -> dict | None:
    """Map en raekke med vilkaarlige kolonnenavne til vores interne feltnavne.
    Returnerer None for tomme/ugyldige raekker (fx en tom raekke nederst i sheetet)."""
    lower_row = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    normalized = {}
    for field, aliases in COLUMN_ALIASES.items():
        value = None
        for alias in aliases:
            if alias in lower_row and str(lower_row[alias]).strip() != "":
                value = lower_row[alias]
                break
        normalized[field] = value

    # G7: kun TYPE er paakraevet. Stoerrelse er nu valgfri, saa boerneting uden
    # t/ med en anden stoerrelsesskala (legetoej, boeger osv.) ogsaa kan staa
    # paa oenskesedlen -- tom stoerrelse betyder "stoerrelse er ikke et kriterie"
    # (se matching._size_rank). En raekke helt uden type er stadig en
    # tom/ufuldstaendig raekke der springes over.
    if not normalized.get("type"):
        return None

    raw_price = normalized.get("maks_pris")
    try:
        price_str = str(raw_price if raw_price is not None else "0")
        price_str = price_str.lower().replace("kr.", "").replace("kr", "").replace(",", ".").strip()
        normalized["maks_pris"] = float(price_str) if price_str else 0.0
    except ValueError:
        logger.warning("Ønskeseddel: ugyldig maks-pris %r i raekke %s, saetter til 0 (udelukker alt)", raw_price, row)
        normalized["maks_pris"] = 0.0

    normalized["maerke"] = str(normalized.get("maerke") or "").strip()
    normalized["type"] = str(normalized["type"]).strip().lower()
    # G7: stoerrelse kan nu vaere None (valgfri) -- guard mod str(None)="None".
    normalized["stoerrelse"] = str(normalized.get("stoerrelse") or "").strip()
    normalized["stand"] = str(normalized.get("stand") or "").strip()
    return normalized


def load_from_local(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw_rows = yaml.safe_load(f) or []
    items = [n for n in (_normalize_row(row) for row in raw_rows) if n]
    logger.info("Ønskeseddel: %d item(s) indlaest fra lokal fil %s", len(items), path)
    return items


def load_from_sheet(spreadsheet, tab_name: str) -> list[dict]:
    try:
        ws = spreadsheet.worksheet(tab_name)
    except Exception:
        logger.warning(
            "Ønskeseddel-fanen '%s' findes ikke i Sheetet endnu -- opret den med "
            "kolonnerne Type/Mærke/Størrelse/Maks-pris/Stand. Ingen items indlaest.",
            tab_name,
        )
        return []

    # J4 (kritikrunde 2026-07-10): raekke 1 i den live fane er nu en rød
    # "denne fane bruges ikke laengere"-advarsel (se BACKLOG.md), ikke
    # kolonne-headeren -- den rigtige header (Type/Mærke/...) staar i raekke 2.
    # Hvis nogen bevidst saetter wishlist.source tilbage til "sheet" skal denne
    # fallback-vej stadig virke uden at fejltolke advarslen som en kolonne-
    # header, saa vi detekterer den og skubber headeren én raekke ned.
    head_row = 1
    try:
        first_cell = str(ws.acell("A1").value or "")
        if first_cell.strip().startswith("⚠️"):
            head_row = 2
            logger.info(
                "Ønskeseddel: advarselsraekke fundet i raekke 1 -- bruger raekke %d som kolonne-header",
                head_row,
            )
    except Exception:
        pass  # kan ikke laese A1 -- fald tilbage til standard head=1, resten af funktionen fanger evt. tomme resultater

    records = ws.get_all_records(head=head_row)

    items = []
    skipped = 0
    for row in records:
        normalized = _normalize_row(row)
        if normalized:
            items.append(normalized)
        elif any(str(v).strip() for v in row.values()):
            # Raekken har INDHOLD (ikke bare en tom raekke nederst i sheetet) men
            # mangler Type/Størrelse -- det er formentlig en tastefejl fra Esbens
            # kone, ikke en tom skabelon-raekke, saa det skal IKKE forsvinde
            # stille (kritik-loop 2: hun fik ellers ingen advarsel om det).
            skipped += 1

    if skipped:
        logger.warning(
            "Ønskeseddel: %d raekke(r) sprunget over (mangler Type/Størrelse) -- SKIPPED_WISHLIST_ROWS=%d",
            skipped, skipped,
        )
    logger.info("Ønskeseddel: %d item(s) indlaest fra Sheet-fane '%s'", len(items), tab_name)
    return items


def load_wishlist(config: dict, spreadsheet=None) -> list[dict]:
    """Indlaeser oenskesedlen ud fra config['wishlist']['source'] -- 'sheet', 'local'
    eller 'turso'. PRODUKTION bruger 'turso' (se config.yaml) -- Sheetets
    "Ønskeseddel"-fane laeses IKKE naar source=turso, se modulets docstring og
    BACKLOG.md's J4-fund. Falder automatisk tilbage til lokal fil hvis 'sheet'
    er valgt men intet spreadsheet er tilgaengeligt, eller hvis 'turso' er
    valgt men Turso-credentials mangler (fx foerste koersel foer opsaetning
    er paa plads)."""
    wl_cfg = config.get("wishlist", {})
    source = wl_cfg.get("source", "local")

    if source == "sheet":
        if spreadsheet is not None:
            return load_from_sheet(spreadsheet, wl_cfg.get("sheet_tab_name", "Ønskeseddel"))
        logger.warning("wishlist.source=sheet men intet spreadsheet tilgaengeligt -- falder tilbage til lokal fil")

    if source == "turso":
        # G5: samme warning-fallback-moenster som "sheet"-grenen ovenfor --
        # falder tilbage til lokal fil hvis Turso-credentials mangler i
        # secrets.env, i stedet for at vaelte resten af scriptet.
        turso_cfg = config.get("turso", {})
        turso_url, token = turso_io.load_turso_config(turso_cfg.get("secrets_path", "secrets.env"))
        if turso_url and token:
            return turso_io.load_wishlist_from_turso(turso_url, token)
        logger.warning("wishlist.source=turso men Turso-credentials mangler i secrets.env -- falder tilbage til lokal fil")

    return load_from_local(wl_cfg.get("local_path", "data/wishlist.local.yaml"))
