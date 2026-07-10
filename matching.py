"""Matching-logik: ranger annoncer mod oenskesedlens items. Se personal-shopper-brief.md §5.

To faser (se monitor.py):
  1. precheck() -- billig foerfiltrering paa kort-niveau-data (titel/stoerrelse/
     pris), FOER vi besoeger en enkelt annoncedetaljeside. Maerke kan ikke
     bekraeftes praecist her (kort-niveau-data har intet separat maerke-felt),
     saa precheck er bevidst lidt for tilladende -- hellere ét ekstra
     detalje-opslag end at misse et godt fund.
  2. match_item()/match_all() -- den fulde ranking NAAR annoncen er beriget med
     rigtigt maerke/stand fra sources/reshopper.py:fetch_details().

Prioritering (brief §5):
  1. Eksakt: type + (maerke hvis angivet) + stoerrelse matcher -> "eksakt"
  2. Naer-match: nabostoerrelser og/eller generisk maerke -> "naer match"
  Alt filtreres FOERST mod maks-pris.
"""
import logging

logger = logging.getLogger("personal_shopper.matching")

# Standard EU boerne-toejstoerrelser i stigende raekkefoelge -- bruges til at
# udlede "nabostoerrelser" (fx 104 -> {98, 110}). Bogstavstoerrelser haenges paa
# for unge/loese produkter (chinos, undertoej mm.), men har ingen numerisk nabo.
SIZE_LADDER = [
    "50", "56", "62", "68", "74", "80", "86", "92", "98", "104", "110", "116",
    "122", "128", "134", "140", "146", "152", "158", "164", "170", "176",
]

# Typer der regnes som synonymer for hinanden ved matching -- Reshoppers egne
# titler blander fx "leggings"/"jeggings", "bukser"/"jeans"/"shorts".
TYPE_SYNONYMS = {
    "leggings": {"leggings", "jeggings", "leggins"},
    "bukser": {"bukser", "jeans", "shorts", "chinos"},
}

GENERIC_BRAND_MARKERS = {"", "ukendt", "unknown", "blandet", "diverse", "no brand"}


def _type_matches(wishlist_type: str, item_title: str) -> bool:
    title_lower = (item_title or "").lower()
    synonyms = TYPE_SYNONYMS.get(wishlist_type, {wishlist_type})
    return any(syn in title_lower for syn in synonyms)


def _neighbor_sizes(size: str) -> set[str]:
    if size not in SIZE_LADDER:
        return set()
    idx = SIZE_LADDER.index(size)
    neighbors = set()
    if idx > 0:
        neighbors.add(SIZE_LADDER[idx - 1])
    if idx < len(SIZE_LADDER) - 1:
        neighbors.add(SIZE_LADDER[idx + 1])
    return neighbors


def _size_rank(wl_size: str, item_size: str) -> str | None:
    # G7: oenske UDEN stoerrelse (fx legetoej, boeger, andre boerneting) --
    # stoerrelse er da ikke et matching-kriterie, saa den blokerer ikke og
    # traekker heller ikke ned til "naer match". Tom oenske-stoerrelse
    # matcher enhver (eller ingen) annonce-stoerrelse som "eksakt".
    wl_size = str(wl_size or "").strip()
    if not wl_size:
        return "eksakt"
    item_size = str(item_size or "").strip()
    if item_size == wl_size:
        return "eksakt"
    if item_size in _neighbor_sizes(wl_size):
        return "naer"
    return None


def precheck(wishlist_item: dict, listing: dict) -> bool:
    """Billig foerfiltrering FOER detalje-opslag: pris, type (via titel), og
    stoerrelse (eksakt eller nabo). Maerke tjekkes IKKE her -- se modulets
    docstring. Bruges af monitor.py til at begraense hvor mange annoncer der
    faar et kostbart detalje-besoeg."""
    if listing.get("price") is None or listing["price"] > wishlist_item["maks_pris"]:
        return False
    if not _type_matches(wishlist_item["type"], listing.get("title", "")):
        return False
    return _size_rank(wishlist_item["stoerrelse"], listing.get("size")) is not None


def _brand_rank(wishlist_brand: str, item_brand: str) -> str | None:
    """Returnerer 'eksakt', 'naer' eller None (ingen match)."""
    wl = (wishlist_brand or "").strip().lower()
    it = (item_brand or "").strip().lower()
    if not wl:
        return "eksakt"  # oensker generisk -- ethvert maerke opfylder kriteriet
    if wl == it:
        return "eksakt"
    if it in GENERIC_BRAND_MARKERS:
        return "naer"  # generisk/ukendt maerke -- naer-match jf. brief §5
    return None


def match_item(wishlist_item: dict, listing: dict) -> dict | None:
    """Fuld matching af en (detalje-beriget) annonce mod ét oenskeseddel-item.
    Returnerer annoncen beriget med match_rank/wishlist-felter, eller None."""
    if listing.get("price") is None or listing["price"] > wishlist_item["maks_pris"]:
        return None
    if not _type_matches(wishlist_item["type"], listing.get("title", "")):
        return None

    size_rank = _size_rank(wishlist_item["stoerrelse"], listing.get("size"))
    if size_rank is None:
        return None

    brand_rank = _brand_rank(wishlist_item.get("maerke", ""), listing.get("brand") or "")
    if brand_rank is None:
        return None

    overall_rank = "eksakt" if (size_rank == "eksakt" and brand_rank == "eksakt") else "naer match"

    enriched = dict(listing)
    enriched["match_rank"] = overall_rank
    enriched["wishlist_type"] = wishlist_item["type"]
    enriched["wishlist_maerke"] = wishlist_item.get("maerke", "")
    enriched["wishlist_stoerrelse"] = wishlist_item["stoerrelse"]
    return enriched


def match_all(wishlist: list[dict], listings: list[dict]) -> list[dict]:
    """Matcher alle (detalje-berigede) annoncer mod alle oenskeseddel-items.
    Samme annonce kan matche flere oenskeseddel-raekker -- den optraeder saa
    én gang pr. match, saa det er tydeligt hvilket oenske et fund daekker.
    Sorteret: eksakte foerst, saa naer-match; billigst foerst inden for hver."""
    matches = []
    for wl_item in wishlist:
        for listing in listings:
            m = match_item(wl_item, listing)
            if m:
                matches.append(m)

    rank_order = {"eksakt": 0, "naer match": 1}
    matches.sort(key=lambda m: (rank_order.get(m["match_rank"], 2), m.get("price", 0)))
    logger.info(
        "Matching: %d match(es) fundet paa tvaers af %d oenskeseddel-item(s) og %d annonce(r)",
        len(matches), len(wishlist), len(listings),
    )
    return matches
