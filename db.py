"""SQLite-persistens for sete/matchede annoncer. Dedup-noegle = hash(source+url).

Samme grundmoenster som PA SPEAKERS-arkivets db.py: ensure_schema() tilfoejer
manglende kolonner via ALTER TABLE, saa en aeldre seen.db opgraderes stille i
stedet for at fejle. Modsat arkivets INSERT OR IGNORE bruger vi her et rigtigt
upsert (ON CONFLICT DO UPDATE) for pris/stand/match_rank/last_seen -- en
annonces pris KAN falde mellem to koersler, og det skal dashboardet afspejle
-- men first_seen forbliver immutabel, saa "hvor laenge har dette vaeret til
salg" altid er paalideligt.

G10 (hastighedsoptimering, 2026-07): brand/size/seller_name/seller_id skrives
KUN ved foerste insert og overskrives ALDRIG paa conflict -- arkitekturen
antager altsaa allerede at disse er stabile egenskaber pr. annonce, ikke noget
der aendrer sig. Det udnytter cached_details_map()/details_fetched-kolonnen
nedenfor til at lade monitor.py springe et helt (dyrt, 5-15s Playwright-
throttlet) fetch_details()-kald over for enhver kandidat-URL vi allerede har
detalje-hentet succesfuldt foer -- kun helt nye annonce-id'er faar det fulde
opslag. 'details_fetched' er en eksplicit succes-markoer (IKKE "brand IS NOT
NULL", fordi et rigtigt/succesfuldt detalje-opslag sagtens KAN give brand=None
naar kilden selv ikke fandt et maerke -- se sources/reshopper.py) og
opgraderes kun 0->1, ALDRIG tilbage til 0, saa en tidligere lykkedes cache-
raekke ikke mistes hvis en efterfoelgende (overfloedig, da den jo allerede er
cachet) skrivning skulle ske uden frisk detalje-data."""
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
    # G16: saelgers land (fx "DK"/"PL"/"SE"), kun udfyldt for Vinted (se
    # sources/vinted.py's fetch_details()) -- NULL for de andre kilder/for
    # Vinted-fund hvor land-opslaget fejlede. Bruges til Esbens oenske om at
    # nedprioritere polske saelgere (dyr fragt + hyppig parfumelugt).
    "seller_country": "TEXT",
    "url": "TEXT",
    "match_rank": "TEXT",
    "wishlist_type": "TEXT",
    "wishlist_maerke": "TEXT",
    "wishlist_stoerrelse": "TEXT",
    "last_seen": "TEXT",
    # G10: 1 naar denne raekkes brand/size/stand/seller_name/seller_id/
    # shipping_price stammer fra et RIGTIGT, lykkedes detalje-opslag (eller en
    # kilde hvor detaljerne allerede laa paa selve soegekortet, se
    # sources/sellpy.py/sources/vinted.py) -- se cached_details_map() og
    # upsert_listing() nedenfor. NULL/0 for raekker hvor detalje-opslaget
    # fejlede (bot-wall, netvaerksfejl) -- disse forsoeges igen naeste koersel.
    "details_fetched": "INTEGER",
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


def cached_details_map(conn: sqlite3.Connection) -> dict:
    """id -> {brand, size, stand, seller_name, seller_id, shipping_price,
    seller_country} for ALLE raekker der har RIGTIGE detalje-data fra et
    tidligere lykkedes detalje-opslag (details_fetched = 1, se
    ADDITIONAL_COLUMNS' kommentar).

    Bruges af monitor.py's run_source() til at springe det dyre (5-15s
    Playwright-throttlet, eller for Vinted: ét land-opslagskald pr. saelger)
    fetch_details()-kald HELT over for kandidat-URL'er vi allerede kender --
    kun helt nye annonce-id'er faar det fulde opslag. Laeses ÉN gang i
    hovedtraaden FOER kilderne koeres parallelt (se main()), og gives
    derefter som et read-only dict til hver kildes worker-traad (samtidig
    laesning af samme dict fra flere traade er sikkert i Python).

    VIGTIGT: prisen tages ALDRIG herfra -- kun brand/size/stand/seller/fragt/
    land. Prisen skal altid komme fra den friske soegeresultat-side, da den
    (modsat de oevrige felter) reelt kan aendre sig fra koersel til koersel."""
    rows = conn.execute(
        "SELECT id, brand, size, stand, seller_name, seller_id, shipping_price, "
        "seller_country FROM listings WHERE details_fetched = 1"
    )
    return {
        row[0]: {
            "brand": row[1],
            "size": row[2],
            "stand": row[3],
            "seller_name": row[4],
            "seller_id": row[5],
            "shipping_price": row[6],
            "seller_country": row[7],
        }
        for row in rows
    }


def upsert_listing(conn: sqlite3.Connection, listing: dict, dry_run: bool = False) -> None:
    """G10: 'listing' skal nu indeholde en 'details_fetched'-noegle (0 eller 1)
    -- se monitor.py's run_source()/main(). Kaldes for BAADE reelle matches OG
    (nyt, G10) enhver kandidat der blev succesfuldt detalje-hentet men IKKE
    matchede noget oenske denne koersel -- saa fremtidige koersler ogsaa kan
    genbruge dens detaljer (lukker det tidligere arkitektur-hul hvor kun
    matches blev cachet). wishlist_type/wishlist_maerke/wishlist_stoerrelse/
    match_rank opdateres nu ogsaa paa conflict (modsat foer G10), saa en
    kandidat der stopper med at matche faar sit match_rank ryddet, og en der
    begynder at matche faar sine wishlist-felter sat -- monitor.py's main()
    sikrer korrekt raekkefoelge (baseline-skrivning FOER match-skrivning) saa
    et reelt match altid 'vinder' inden for samme koersel."""
    if dry_run:
        return
    listing = dict(listing)
    listing.setdefault("seller_country", None)
    conn.execute(
        """
        INSERT INTO listings
            (id, source, item_id, title, brand, size, price, stand, seller_name,
             seller_id, shipping_price, url, match_rank, wishlist_type,
             wishlist_maerke, wishlist_stoerrelse, first_seen, last_seen,
             details_fetched, seller_country)
        VALUES
            (:id, :source, :item_id, :title, :brand, :size, :price, :stand, :seller_name,
             :seller_id, :shipping_price, :url, :match_rank, :wishlist_type,
             :wishlist_maerke, :wishlist_stoerrelse, :first_seen, :last_seen,
             :details_fetched, :seller_country)
        ON CONFLICT(id) DO UPDATE SET
            price = excluded.price,
            stand = excluded.stand,
            match_rank = excluded.match_rank,
            shipping_price = excluded.shipping_price,
            last_seen = excluded.last_seen,
            wishlist_type = excluded.wishlist_type,
            wishlist_maerke = excluded.wishlist_maerke,
            wishlist_stoerrelse = excluded.wishlist_stoerrelse,
            details_fetched = CASE
                WHEN excluded.details_fetched = 1 THEN 1
                ELSE listings.details_fetched
            END,
            -- G16: modsat brand/seller_name/seller_id (stabile identitets-
            -- felter, se modulets docstring) OPDATERES seller_country ved
            -- hver koersel der reelt fandt et land -- undgaar at et FOERSTE
            -- mislykkedes land-opslag (NULL) laaser raekken fast for altid,
            -- selvom en senere koersel finder det rigtige land.
            seller_country = CASE
                WHEN excluded.seller_country IS NOT NULL THEN excluded.seller_country
                ELSE listings.seller_country
            END
        """,
        listing,
    )
    conn.commit()
