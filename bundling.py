"""Bundling: gruppér matches pr. saelger og beregn fragt-oekonomi. Se
personal-shopper-brief.md §6 -- dette er kernen i businesscasen.

Kerneidé: én saelger, flere matchende items -> ÉN fragt for hele koebet i
stedet for én fragt pr. item. Effektiv pris/stk falder markant naar man kan
samle flere smaa/billige items hos samme saelger (brief-eksempel: 4 bodyer
à 20 kr. + 45 kr. fragt = 26 kr./stk. i stedet for 65 kr./stk. hver for sig).
"""
import logging
from collections import defaultdict

logger = logging.getLogger("personal_shopper.bundling")


def _seller_key(match: dict) -> str:
    """Saelger-ID hvis vi kunne udtraekke det (se sources/reshopper.py og
    sources/dba.py), ellers saelgernavn som fallback-groupnoegle (IKKE
    garanteret unikt paa tvaers af én platform -- flere saelgere kan dele
    fornavn+forbogstav -- men bedste tilgaengelige signal naar det
    best-effort ID-udtraek fejler).

    VIGTIGT (G1, DBA-tilfoejelse): noeglen praefikses ALTID med kilden.
    En Reshopper-saelger og en DBA-saelger med samme navn (eller endda
    samme numeriske ID paa hver deres platform, rent tilfaeldigt) er IKKE
    noedvendigvis samme person -- de har adskilte konti paa adskilte
    platforme, saa bundling paa tvaers af kilder ville foreslaa at samle
    et koeb hos "én saelger" der reelt kraever to separate handler/fragter."""
    source = (match.get("source") or "ukendt_kilde").strip().lower()
    seller_id = match.get("seller_id")
    if seller_id:
        return f"{source}|id:{seller_id}"
    return f"{source}|navn:{(match.get('seller_name') or 'ukendt').strip().lower()}"


def build_bundles(matches: list[dict], default_shipping_dkk: float = 39.0) -> list[dict]:
    """Grupperer matches pr. saelger og beregner bundle-oekonomi.
    Returnerer bundle-dicts sorteret efter stoerst besparelse pr. item foerst."""
    by_seller = defaultdict(list)
    for m in matches:
        by_seller[_seller_key(m)].append(m)

    bundles = []
    for seller_key, seller_matches in by_seller.items():
        # Dedupliker paa item_id -- samme fysiske annonce kan optraede flere
        # gange hvis den matcher flere oenskeseddel-raekker (se matching.py).
        unique_items = {}
        for m in seller_matches:
            unique_items.setdefault(m.get("item_id") or m.get("url"), m)
        items = list(unique_items.values())
        count = len(items)
        if count == 0:
            continue

        shipping_values = [m.get("shipping_price") for m in items if m.get("shipping_price") is not None]
        if shipping_values:
            # Fragt er pr. ORDRE, ikke pr. item -- vi antager saelgerens fragtpris
            # er ens paa tvaers af egne annoncer. Bruger den hoejeste observerede
            # vaerdi som et konservativt (ikke-optimistisk) bud paa den reelle pris.
            shipping = max(shipping_values)
            shipping_is_assumed = False
        else:
            shipping = default_shipping_dkk
            shipping_is_assumed = True

        total_item_price = sum(m["price"] for m in items)
        total_with_shipping = total_item_price + shipping
        effective_price_per_item = round(total_with_shipping / count, 2)
        alone_price_per_item = round(sum(m["price"] + shipping for m in items) / count, 2)
        savings_per_item = round(alone_price_per_item - effective_price_per_item, 2)

        bundles.append({
            "seller_key": seller_key,
            "source": items[0].get("source", "ukendt_kilde"),
            "seller_name": items[0].get("seller_name", "ukendt"),
            "seller_id": items[0].get("seller_id"),
            "item_count": count,
            "items": items,
            "total_item_price": round(total_item_price, 2),
            "shipping_dkk": shipping,
            "shipping_is_assumed": shipping_is_assumed,
            "total_with_shipping": round(total_with_shipping, 2),
            "effective_price_per_item": effective_price_per_item,
            "alone_price_per_item": alone_price_per_item,
            "savings_per_item": savings_per_item,
            "bundle_worth_it": count >= 2,
            # Lokal afhentning-bonus: KUN naar vi har positiv bekraeftelse af 0-kr
            # fragt fra schema.org-dataen -- manglende fragt-info er IKKE det samme
            # som bekraeftet gratis afhentning (kan ogsaa vaere manglende data).
            "local_pickup_bonus": (not shipping_is_assumed) and shipping == 0,
        })

    # En "bundle" giver kun mening med 2+ items -- ellers er der ingen delt
    # fragt at spare, og det er reelt bare et enkelt match (som allerede staar
    # i Matches-listen). Enkelt-item-saelgere frafiltreres her, saa
    # bundle-tallet baade i webappen, Sheets og status-teksten er ægte antal
    # bundles (Esben-oenske 2026-07-10). Enkelt-matchene mistes IKKE -- de er
    # stadig i all_matches / Matches-visningen.
    sellers_with_match = len(bundles)
    bundles = [b for b in bundles if b["item_count"] >= 2]
    bundles.sort(key=lambda b: (-b["savings_per_item"], -b["item_count"]))
    logger.info(
        "Bundling: %d saelger(e) med mindst ét match, heraf %d ægte bundle(s) (2+ items)",
        sellers_with_match, len(bundles),
    )
    return bundles
