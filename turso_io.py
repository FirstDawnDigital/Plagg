"""turso_io.py -- HTTP-only IO mod Turso (G5). Spejler sheets_output.py's rolle:
monitor.py/trigger_watcher.py kan laese/skrive wishlist, matches, bundles og
kontrolpanel-status uden Google Sheets, via Tursos /v2/pipeline HTTP-API --
samme moenster som ejendompython/webapp/turso_sync.py. Ingen turso CLI/OAuth
noedvendig, kun TURSO_URL + TURSO_AUTH_TOKEN fra secrets.env.

Fase 1 (se plan): denne fil roerer INTET i monitor.py/wishlist.py/Sheets --
den er bygget og testet isoleret foerst.

Generations-swap (matches/bundles): hver koersel allokerer et nyt run_id,
indsaetter nye rækker tagget med det, og publicerer FOERST derefter atomisk
via control.current_run_id. Det undgaar at en frontend-laeser rammer et tomt
vindue midt i en overskrivning, og beskytter mod at to overlappende
monitor.py-koersler race'r hinanden (se CREATE TABLE-kommentarerne nedenfor
og planens "Turso-skema"-afsnit for den fulde begrundelse).
"""
import json
import logging
import os
import urllib.error
import urllib.request

from sheets_output import build_tldr_line  # noqa: F401 -- genbruges uaendret af kaldere (ikke af denne fil selv)

logger = logging.getLogger("personal_shopper.turso_io")

# Maks antal INSERTs per HTTP-request, samme graense som
# ejendompython/webapp/turso_sync.py bruger (Tursos ~10 MB request-limit).
BATCH_SIZE = 200

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS wishlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL, maerke TEXT NOT NULL DEFAULT '',
        stoerrelse TEXT NOT NULL, maks_pris REAL NOT NULL DEFAULT 0,
        stand TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS matches (
        run_id INTEGER NOT NULL, db_id TEXT, url TEXT NOT NULL, item_id TEXT,
        source TEXT NOT NULL, title TEXT, match_rank TEXT, price REAL,
        size TEXT, brand TEXT, stand TEXT, seller_name TEXT, seller_id TEXT,
        wishlist_type TEXT, wishlist_maerke TEXT, wishlist_stoerrelse TEXT,
        shipping_price REAL, first_seen TEXT, seller_country TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_matches_run_id ON matches(run_id)",
    """CREATE TABLE IF NOT EXISTS bundles (
        run_id INTEGER NOT NULL, seller_key TEXT NOT NULL, seller_name TEXT,
        seller_id TEXT, source TEXT NOT NULL, item_count INTEGER,
        items_json TEXT NOT NULL, total_item_price REAL, shipping_dkk REAL,
        shipping_is_assumed INTEGER, total_with_shipping REAL,
        effective_price_per_item REAL, alone_price_per_item REAL,
        savings_per_item REAL, bundle_worth_it INTEGER, local_pickup_bonus INTEGER,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_bundles_run_id ON bundles(run_id)",
    """CREATE TABLE IF NOT EXISTS control (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        run_now INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'Klar',
        last_run_at TEXT, last_tldr TEXT,
        current_run_id INTEGER NOT NULL DEFAULT 0,
        next_run_id INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "INSERT OR IGNORE INTO control (id) VALUES (1)",
]


def load_turso_config(secrets_path: str = "secrets.env") -> tuple[str, str]:
    """Henter TURSO_URL og TURSO_AUTH_TOKEN fra secrets_path eller miljoevariabler.
    Manuel 'KEY=value'-linje-parsing + miljoevariabel-override, identisk moenster
    med ejendompython/webapp/turso_sync.py:load_turso_config() -- ingen
    python-dotenv-afhaengighed."""
    url = token = ""
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TURSO_URL="):
                    url = line.split("=", 1)[1].strip()
                elif line.startswith("TURSO_AUTH_TOKEN="):
                    token = line.split("=", 1)[1].strip()
    url = os.environ.get("TURSO_URL", url)
    token = os.environ.get("TURSO_AUTH_TOKEN", token)
    return url, token


def _endpoint(turso_url: str) -> str:
    return turso_url.replace("libsql://", "https://") + "/v2/pipeline"


def _typed_arg(value):
    """Konverterer en Python-vaerdi til Tursos typed-arg-form
    ({"type": "text"/"integer"/"float"/"null", "value": ...}), samme princip
    som cloudflare/worker.js's tursoExecute()-kald bruger paa JS-siden."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _pipeline(turso_url: str, token: str, statements: list[dict]) -> list:
    """Sender en liste af {'sql': ..., 'args': [...]}-statements til Tursos
    /v2/pipeline i én HTTP-request. Returnerer den raa 'results'-liste.
    Kaster RuntimeError ved HTTP- eller SQL-fejl -- kaldere haandterer selv
    try/except hvor en fejl her ikke maa vaere fatal (samme moenster som
    sheets_output.py's Sheets-kald)."""
    body_requests = [
        {"type": "execute", "stmt": {"sql": s["sql"], "args": [_typed_arg(a) for a in s.get("args", [])]}}
        for s in statements
    ]
    body_requests.append({"type": "close"})
    body = json.dumps({"requests": body_requests}).encode("utf-8")
    req = urllib.request.Request(
        _endpoint(turso_url),
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Turso HTTP {e.code}: {e.read().decode()[:300]}")

    results = data.get("results", [])
    for i, result in enumerate(results):
        if result.get("type") == "error":
            msg = result.get("error", {}).get("message", "ukendt fejl")
            raise RuntimeError(f"Turso SQL-fejl i statement {i}: {msg}")
    return results


def _rows_as_dicts(result: dict) -> list[dict]:
    """Konverterer ét /v2/pipeline execute-resultat til en liste af dicts
    (kolonnenavn -> vaerdi), samme udpakning som worker.js's tursoExecute()."""
    res = result["response"]["result"]
    cols = [c["name"] for c in res["cols"]]
    rows = []
    for row in res["rows"]:
        d = {}
        for name, cell in zip(cols, row):
            d[name] = None if (cell is None or cell.get("type") == "null") else cell.get("value")
        rows.append(d)
    return rows


def _num(value, cast):
    """None -> None, ellers cast(value). Bruges til at give REAL/INTEGER-
    kolonner det rigtige typed-arg selv naar kilde-dictet har en streng eller
    slet ikke har feltet."""
    return None if value is None else cast(value)


def ensure_schema(turso_url: str, token: str) -> None:
    """CREATE TABLE IF NOT EXISTS x4 + INSERT OR IGNORE control-singleton.
    Idempotent, tænkt kaldt hver monitor.py-koersel.

    G16: 'seller_country' er en NY kolonne paa en tabel der allerede findes
    i PRODUKTION (den live Turso-database) -- CREATE TABLE IF NOT EXISTS
    roerer IKKE en eksisterende tabel, saa kolonnen tilfoejes separat via
    PRAGMA table_info + ALTER TABLE (samme idempotente moenster som
    db.py:ensure_schema() bruger for den lokale SQLite-db)."""
    _pipeline(turso_url, token, [{"sql": s, "args": []} for s in SCHEMA_STATEMENTS])
    _ensure_matches_seller_country_column(turso_url, token)
    logger.info("Turso: skema bekraeftet/oprettet")


def _ensure_matches_seller_country_column(turso_url: str, token: str) -> None:
    result = _pipeline(turso_url, token, [{"sql": "PRAGMA table_info(matches)", "args": []}])
    existing_columns = {row["name"] for row in _rows_as_dicts(result[0])}
    if "seller_country" not in existing_columns:
        _pipeline(turso_url, token, [
            {"sql": "ALTER TABLE matches ADD COLUMN seller_country TEXT", "args": []},
        ])
        logger.info("Turso: 'seller_country'-kolonne tilfoejet til matches (G16)")


def load_wishlist_from_turso(turso_url: str, token: str) -> list[dict]:
    """SELECT * FROM wishlist -> samme dict-form som wishlist.py's
    _normalize_row() returnerer, saa matching.py/bundling.py er uaendrede."""
    results = _pipeline(turso_url, token, [{"sql": "SELECT * FROM wishlist ORDER BY id", "args": []}])
    items = []
    for row in _rows_as_dicts(results[0]):
        items.append({
            "type": str(row.get("type") or "").strip().lower(),
            "maerke": str(row.get("maerke") or "").strip(),
            "stoerrelse": str(row.get("stoerrelse") or "").strip(),
            "maks_pris": float(row.get("maks_pris") or 0),
            "stand": str(row.get("stand") or "").strip(),
        })
    logger.info("Oenskeseddel: %d item(s) indlaest fra Turso", len(items))
    return items


def write_matches_and_bundles(
    turso_url: str, token: str, matches: list[dict], bundles: list[dict],
    first_seen_lookup: dict, now_iso: str, tldr_text: str,
) -> tuple[int, int]:
    """Generations-swap (se modulets docstring og planens 'Turso-skema'-afsnit):
      1. Laes det NUVAERENDE current_run_id ("superseded_run_id") og allokér
         SAMTIDIG et nyt run_id via control.next_run_id -- intet synligt
         aendres endnu.
      2. INSERT nye matches/bundles-rækker tagget med det nye run_id, i batches.
      3. Atomisk publicér: current_run_id (+ last_tldr) opdateres KUN hvis dette
         run_id er nyere end det der allerede er publiceret (guard mod race
         mellem to overlappende koersler) -- RETURNING bruges til at se om
         guarden reelt lod opdateringen ske.
      4. Oprydning: KUN hvis vi selv rent faktisk blev publiceret som current
         ovenfor, sletter vi PRAECIS den generation vi selv erstattede
         (superseded_run_id fra trin 1) -- ALDRIG et bredere "alt der ikke er
         run_id" (se G5-FIX fund #2 nedenfor for hvorfor).

    G5-FIX (kritisk fund #2 -- race condition): den tidligere oprydning brugte
    "DELETE ... WHERE run_id != (SELECT current_run_id FROM control)", dvs.
    den slettede ALT der ikke matchede det GLOBALT nyeste current_run_id paa
    oprydningstidspunktet. Hvis to koersler (A og E) overlapper, og E naar at
    indsaette+publicere sine raekker FOER A's (langsommere) oprydning naar at
    koere, ville A's brede DELETE ramme E's allerede-publicerede raekker (fordi
    A kun kendte sit EGET run_id, ikke E's) -- eller omvendt kunne A's
    oprydning ramme E's endnu-ikke-publicerede raekker foer E selv naaede at
    publicere, saa E's efterfoelgende publish pegede paa 0 raekker. Fixet:
    hver skriver sletter KUN den ene generation den selv erstattede (sit eget
    "superseded_run_id", laest FOER den allokerede sit eget run_id), og kun
    hvis dens EGEN publicering rent faktisk slog igennem. Det garanterer at en
    skriver aldrig kan roere en anden samtidig skrivers raekker, uanset
    rækkefoelge -- paa bekostning af at en (sjaelden) tabt generation kan
    blive "forældreløs" og ikke ryddet op med det samme, hvilket er et langt
    mindre problem end datatab.
    tldr_text = genbrug sheets_output.build_tldr_line(bundles) direkte (ren
    Python, ingen Sheets-kobling) -> gemmes i control.last_tldr.
    Returnerer (antal matches skrevet, antal bundles skrevet)."""
    alloc = _pipeline(turso_url, token, [
        {"sql": "SELECT current_run_id FROM control WHERE id = 1", "args": []},
        {"sql": "UPDATE control SET next_run_id = next_run_id + 1 WHERE id = 1 RETURNING next_run_id", "args": []},
    ])
    superseded_run_id = int(_rows_as_dicts(alloc[0])[0]["current_run_id"])
    run_id = int(_rows_as_dicts(alloc[1])[0]["next_run_id"])

    match_stmts = []
    for m in matches:
        db_id = m.get("_db_id") or m.get("db_id")
        first_seen = first_seen_lookup.get(db_id, now_iso)
        match_stmts.append({
            "sql": """INSERT INTO matches
                (run_id, db_id, url, item_id, source, title, match_rank, price,
                 size, brand, stand, seller_name, seller_id, wishlist_type,
                 wishlist_maerke, wishlist_stoerrelse, shipping_price, first_seen,
                 seller_country)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            "args": [
                run_id, db_id, m.get("url"), m.get("item_id"), m.get("source"),
                m.get("title"), m.get("match_rank"), _num(m.get("price"), float),
                m.get("size"), m.get("brand"), m.get("stand"), m.get("seller_name"),
                m.get("seller_id"), m.get("wishlist_type"), m.get("wishlist_maerke"),
                m.get("wishlist_stoerrelse"), _num(m.get("shipping_price"), float),
                first_seen, m.get("seller_country"),
            ],
        })
    for i in range(0, len(match_stmts), BATCH_SIZE):
        batch = match_stmts[i:i + BATCH_SIZE]
        if batch:
            _pipeline(turso_url, token, batch)

    bundle_stmts = []
    for b in bundles:
        bundle_stmts.append({
            "sql": """INSERT INTO bundles
                (run_id, seller_key, seller_name, seller_id, source, item_count,
                 items_json, total_item_price, shipping_dkk, shipping_is_assumed,
                 total_with_shipping, effective_price_per_item, alone_price_per_item,
                 savings_per_item, bundle_worth_it, local_pickup_bonus)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            "args": [
                run_id, b.get("seller_key"), b.get("seller_name"), b.get("seller_id"),
                b.get("source"), _num(b.get("item_count"), int),
                json.dumps(b.get("items", []), ensure_ascii=False),
                _num(b.get("total_item_price"), float), _num(b.get("shipping_dkk"), float),
                bool(b.get("shipping_is_assumed")), _num(b.get("total_with_shipping"), float),
                _num(b.get("effective_price_per_item"), float), _num(b.get("alone_price_per_item"), float),
                _num(b.get("savings_per_item"), float), bool(b.get("bundle_worth_it")),
                bool(b.get("local_pickup_bonus")),
            ],
        })
    for i in range(0, len(bundle_stmts), BATCH_SIZE):
        batch = bundle_stmts[i:i + BATCH_SIZE]
        if batch:
            _pipeline(turso_url, token, batch)

    # Atomisk publicér -- guarden (current_run_id < run_id) forhindrer en
    # langsommere AELDRE koersel i at overskrive en nyere koersels resultat
    # hvis de to overlapper i tid. last_tldr opdateres i SAMME guardede
    # UPDATE, saa en tabt raceren heller ikke faar lov at overskrive en
    # nyere TL;DR-tekst. RETURNING fortaeller os om guarden reelt lod
    # opdateringen ske (tom raekke tilbage = vi tabte raceren -- en anden,
    # nyere koersel er allerede blevet publiceret).
    publish_result = _pipeline(turso_url, token, [
        {
            "sql": "UPDATE control SET current_run_id = ?, last_tldr = ? WHERE id = 1 AND current_run_id < ? RETURNING current_run_id",
            "args": [run_id, tldr_text, run_id],
        },
    ])
    we_are_published = len(_rows_as_dicts(publish_result[0])) > 0

    # Oprydning: KUN hvis VI selv blev publiceret ovenfor, og KUN den ene
    # PRAECISE generation vi selv erstattede (superseded_run_id, laest foer vi
    # allokerede vores eget run_id). Aldrig et bredere "alt andet end nyeste"
    # -- se G5-FIX fund #2 i docstringen ovenfor. Hvis vi tabte raceren
    # (we_are_published=False) rydder vi slet ikke op -- vores data er ikke
    # blevet current, og superseded_run_id kan i saa fald vaere forkert
    # (en anden koersel kan have naaet at aendre current_run_id imellem vores
    # laesning og vores (mislykkede) publicering).
    if we_are_published:
        try:
            _pipeline(turso_url, token, [
                {"sql": "DELETE FROM matches WHERE run_id = ?", "args": [superseded_run_id]},
                {"sql": "DELETE FROM bundles WHERE run_id = ?", "args": [superseded_run_id]},
            ])
        except Exception:
            logger.warning("Turso: oprydning af erstattet generation (run_id=%s) fejlede (ikke kritisk)", superseded_run_id, exc_info=True)
    else:
        logger.warning(
            "Turso: run_id=%d blev IKKE publiceret (en nyere koersel vandt raceren) -- springer oprydning over "
            "for ikke at roere en anden koersels data", run_id,
        )

    logger.info("Turso: run_id=%d skrevet (%d match(es), %d bundle(s))", run_id, len(matches), len(bundles))
    return len(matches), len(bundles)


def read_run_now(turso_url: str, token: str) -> bool:
    """Laeser control.run_now -- True hvis Esbens kone har trykket 'Koer nu'."""
    results = _pipeline(turso_url, token, [{"sql": "SELECT run_now FROM control WHERE id = 1", "args": []}])
    rows = _rows_as_dicts(results[0])
    if not rows:
        return False
    return bool(int(rows[0]["run_now"] or 0))


def set_status(turso_url: str, token: str, text: str) -> None:
    """Opdaterer control.status (fx 'Koerer...') uden at roere run_now/last_run_at."""
    _pipeline(turso_url, token, [
        {"sql": "UPDATE control SET status = ?, updated_at = datetime('now') WHERE id = 1", "args": [text]},
    ])


def finish_run(turso_url: str, token: str, status_text: str, last_run_text: str) -> None:
    """Nulstiller run_now, saetter status + last_run_at -- kaldes naar en
    'Koer nu'-koersel er faerdig (samme moenster som trigger_watcher.py's
    eksisterende Sheets-flow)."""
    _pipeline(turso_url, token, [
        {
            "sql": "UPDATE control SET run_now = 0, status = ?, last_run_at = ?, updated_at = datetime('now') WHERE id = 1",
            "args": [status_text, last_run_text],
        },
    ])
