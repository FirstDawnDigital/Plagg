"""SQLite-persistens for sete/matchede annoncer. Dedup-noegle = hash(source+url).

Samme grundmoenster som PA SPEAKERS-arkivets db.py: ensure_schema() tilfoejer
manglende kolonner via ALTER TABLE, saa en aeldre seen.db opgraderes stille i
stedet for at fejle. Modsat arkivets INSERT OR IGNORE bruger vi her et rigtigt
upsert (ON CONFLICT DO UPDATE) for pris/stand/match_rank/last_seen -- en
annonces pris KAN falde mellem to koersler, og det skal dashboardet afspejle
-- men first_seen forbliver immutabel, saa "hvor laenge har dette vaeret til
salg" altid er paalideligt."""
import hashlib
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    first_seen TEXT NOT NULL
)
"""

ADDITIONAL_COLUMNS = {
    "item_id": "TEXT",
    "title": "TEXT",
    "brand": "TEXT",
    "size": "TEXT",
    "price": "REAL",
    "stand": "TEXT",
    "seller_name": "TEXT",
    "seller_id": "TEXT",
    "shipping_price": "REAL",
    "url": "TEXT",
    "match_rank": "TEXT",
    "wishlist_type": "TEXT",
    "wishlist_maerke": "TEXT",
    "wishlist_stoerrelse": "TEXT",
    "last_seen": "TEXT",
}


def make_id(source: str, url: str) -> str:
    return hashlib.sha256(f"{source}|{url}".encode("utf-8")).hexdigest()[:32]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(listings)")}
    for column, sql_type in ADDITIONAL_COLUMNS.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {column} {sql_type}")
    conn.commit()


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


def first_seen_map(conn: sqlite3.Connection) -> dict:
    """id -> first_seen (ISO-tidsstempel), til brug foer upsert saa vi kan vise
    'foerste gang set' korrekt i dashboardet selv for allerede-kendte annoncer."""
    return {row[0]: row[1] for row in conn.execute("SELECT id, first_seen FROM listings")}


def upsert_listing(conn: sqlite3.Connection, listing: dict, dry_run: bool = False) -> None:
    if dry_run:
        return
    conn.execute(
        """
        INSERT INTO listings
            (id, source, item_id, title, brand, size, price, stand, seller_name,
             seller_id, shipping_price, url, match_rank, wishlist_type,
             wishlist_maerke, wishlist_stoerrelse, first_seen, last_seen)
        VALUES
            (:id, :source, :item_id, :title, :brand, :size, :price, :stand, :seller_name,
             :seller_id, :shipping_price, :url, :match_rank, :wishlist_type,
             :wishlist_maerke, :wishlist_stoerrelse, :first_seen, :last_seen)
        ON CONFLICT(id) DO UPDATE SET
            price = excluded.price,
            stand = excluded.stand,
            match_rank = excluded.match_rank,
            shipping_price = excluded.shipping_price,
            last_seen = excluded.last_seen
        """,
        listing,
    )
    conn.commit()
