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
import re

logger = logging.getLogger("personal_shopper.matching")

# Standard EU boerne-toejstoerrelser i stigende raekkefoelge -- bruges til at
# udlede "nabostoerrelser" (fx 104 -> {98, 110}). Bogstavstoerrelser haenges paa
# for unge/loese produkter (chinos, undertoej mm.), men har ingen numerisk nabo.
SIZE_LADDER = [
    "50", "56", "62", "68", "74", "80", "86", "92", "98", "104", "110", "116",
    "122", "128", "134", "140", "146", "152", "158", "164", "170", "176",
]

# G18 (2026-07-11): FULD boernetoejs-type-taksonomi. Kilde: Sellpys Algolia-
# facet ('metadata.type', segment=children) gav 200 DISTINKTE, kontrollerede
# danske typebetegnelser (saelgeren vaelger fra en dropdown, ikke fritekst) --
# den mest autoritative "type tree" vi har adgang til paa tvaers af de 4
# kilder (Reshopper har INGEN separat type-facet, kun Alder/Koen/Stoerrelse/
# Maerke/Stand -- bekraeftet ved DOM-inspektion 2026-07-11). Danske
# SAMMENSAETNINGER (fx "vinterjakke", "softshelljakke") daekkes allerede af
# almindelig substring-matching (de INDEHOLDER "jakke") og kraever ingen
# saerskilt klynge-medlemskab -- klyngerne nedenfor daekker KUN (a) danske
# ord der IKKE deler en faelles rod (fx "anorak"/"parka" er ikke "jakke"-
# sammensaetninger) og (b) fremmedsprogede ord fra Vinteds internationale
# saelgere (svensk/polsk/finsk observeret direkte i danske soegeresultater,
# se G16). Fremmedords-STAMMER (ikke hele ord) bruges hvor boejning varierer
# -- fx polsk "kurtk" fanger kurtka/kurtki/kurtek/kurtkę.
#
# LIVE-VERIFICERET 2026-07-11 (se BACKLOG.md's G18 for detaljer): "Kuling
# jacka"/"skaljacka" (svensk jakke), "kurtka"/"kurtka przejściowa" (polsk
# jakke, mange traeff), "tröja"/"tröja med krage" (svensk troeje, mange
# traeff), "byxor"/"cykelbyxa" (svensk bukser), "spodnie" (polsk bukser,
# bekraeftet tidligere i G16-arbejdet), "sukienka" (polsk kjole, mange
# traeff), "zestaw" (polsk saet), "buty"/"sneakersy" (polsk sko, mange
# traeff), "kuoritakki"/"softshelltakki" (finsk jakke).
#
# De resterende ~150 Sellpy-typer (primaert tilbehoer -- Vanter, Rygsaek,
# Solbriller, Halskaede osv. -- og meget specifikke sport-/sko-undertyper)
# er IKKE klyngede eksplicit: de matcher stadig via det almindelige literal-
# ord-fallback (samme adfaerd som foer denne aendring), og er lavere
# prioritet at fremmedsprogs-daekke (enten sjaeldne oenskesedler-typer eller
# allerede internationale laaneord som "Blazer"/"Bikini"/"Body").
_TYPE_CLUSTERS = [
    # Jakker/frakker (AEGTE ord-varianter -- IKKE "vest", som er sit eget,
    # aermeloese, cluster nedenfor, jf. Sellpys egen adskillelse).
    {"jakke", "frakke", "parka", "anorak", "jacka", "takki", "kuoritakki", "kurtk"},
    {"vest", "ydervest", "dunvest"},
    # Bukser (leggings er en SEPARAT klynge, se nedenfor -- Esbens
    # oenskeseddel behandler dem bevidst forskelligt).
    {"bukser", "jeans", "shorts", "chinos", "kuloty", "byx", "spodni"},
    {"leggings", "jeggings", "leggins", "treggings"},
    # Kjoler/nederdele (Sellpy adskiller "Kjole" og "Nederdel", men de
    # daekkes af samme klynge -- svensk skelner ogsaa mellem "klänning"
    # (kjole) og "kjol" (nederdel), begge relevante for dette oenske).
    {"kjole", "nederdel", "sukienk", "klänning", "kjol"},
    # Troejer/sweatere (varmt, afslappet overdel)
    {"trøje", "sweater", "hættetrøje", "sweatshirt", "cardigan", "pullover", "tröj"},
    # T-shirts/toppe (koligere, aermeloes/kortaermet overdel -- bevidst
    # IKKE samme klynge som troeje/sweater ovenfor)
    {"t-shirt", "tshirt", "tanktop", "top", "croptop"},
    # Skjorter/bluser (knap-/vaeve-stof-overdel, adskilt fra t-shirt/troeje)
    {"skjorte", "bluse", "tunika", "koszulk"},
    # Saet/heldragter
    {"sæt", "sparkedragt", "buksedragt", "heldragt", "dragt", "zestaw", "paczk"},
    # Sko/fodtoej (bredt -- enhver fodtoejstype er relevant for et generisk
    # "sko"-oenske)
    {"sko", "sneakers", "støvler", "sandaler", "tøfler", "buty", "skor"},
    # Hovedbeklaedning
    {"hue", "kasket", "hat", "mössa", "czapk"},
]


def _build_type_synonyms(clusters: list) -> dict:
    """Udvider klynger til et fladt opslags-dict: hvert ord i en klynge
    peger paa HELE klyngens ordsaet, saa uanset hvilket ord i klyngen
    oensket-typen bruger, faar man samme brede synonym-daekning (fx et
    oenske om 'sweatshirt' matcher ogsaa 'hættetrøje'/'cardigan'/svensk
    'tröja', ikke kun praecis 'sweatshirt')."""
    synonyms = {}
    for cluster in clusters:
        for word in cluster:
            synonyms[word] = cluster
    return synonyms


# Typer der regnes som synonymer for hinanden ved matching -- se _TYPE_CLUSTERS
# ovenfor for kilder/begrundelse. Reshoppers/DBAs/Sellpys/Vinteds egne titler
# blander frit fx "leggings"/"jeggings", "bukser"/"jeans"/"shorts", samt nu
# ogsaa fremmedsprogede varianter fra Vinteds internationale saelgere.
TYPE_SYNONYMS = _build_type_synonyms(_TYPE_CLUSTERS)

GENERIC_BRAND_MARKERS = {"", "ukendt", "unknown", "blandet", "diverse", "no brand"}

# G16: Esben har observeret at polske Vinted-saelgere ofte har dyr fragt OG
# hyppig parfumelugt paa toejet -- IKKE en hard eksklusion (varen kan sagtens
# vaere et godt fund alligevel), kun en SOFT nedprioritering i sorteringen +
# en synlig advarsel, saa Esbens kone selv kan vurdere. 'seller_country'
# kommer fra sources/vinted.py's fetch_details() (se dens G16-fund) -- tomt/
# ukendt land (andre kilder, eller et fejlet Vinted-land-opslag) paavirker
# ALDRIG sorteringen.
DEPRIORITIZED_SELLER_COUNTRIES = {"PL"}
COUNTRY_WARNING_TEXT = "⚠️ Polsk sælger – ofte dyr fragt + parfumelugt"

# G6: 5-trins normaliseret stand-skala paa tvaers af Reshopper/DBA/Sellpy/
# Vinted -- hver platform bruger sin egen fritekst-formulering (Reshopper
# "Helt ny"/"Næsten som ny"/"God, men brugt"/"Defekt, kan laves"; Sellpy
# "Nyt"/"Meget god"/"God"/"Acceptabelt"; Vinted "Ny med prismærker"/"Meget
# god"/"God"/...; DBA fritekst-extra + samme CONDITION_MAP-fallback som
# Reshopper). Rangeret bedst (0) til vaerst (4) -- KUN raekkefoelgen taeller.
STAND_TIERS = ["ny", "naesten_ny", "god", "brugt", "defekt"]
STAND_TIER_RANK = {tier: i for i, tier in enumerate(STAND_TIERS)}
STAND_TIER_LABELS = {
    "ny": "Ny", "naesten_ny": "Næsten som ny", "god": "God",
    "brugt": "Brugt", "defekt": "Defekt",
}

# Keyword-heuristik i stedet for en fast per-kilde opslagstabel. RETTELSE
# (2026-07-11, live verificeret mod ~30 rigtige DBA-annoncer): DBAs "Stand"-
# extra er IKKE fritekst som tidligere antaget her -- den har et 'valueId'
# (1/2/3 observeret: "Helt ny - uåbnet/med prismærke" / "Som ny - ingen
# synlige brugsspor" / "Brugt - men i god stand"), dvs. en fast facet paa
# DBAs eget opslagsformular, ligesom Reshoppers KNOWN_STAND_LABELS. Keyword-
# heuristikken bruges alligevel (frem for en per-kilde opslagstabel) fordi
# den ALLEREDE klassificerer alle 3 kendte DBA-vaerdier korrekt, og fordi
# den robust daekker fremtidige formuleringsaendringer paa alle 4 platforme
# uden kode-aendring. RAEKKEFOELGEN er
# vigtig: mest specifikke/alvorlige moenstre proeves FOERST, saa en streng
# med flere keywords (fx "God, men brugt") rammer det rigtige tier foerst i
# stedet for at et senere "brugt"-keyword fejlagtigt overtrumfer "god".
_STAND_PATTERNS = [
    (re.compile(r"defekt|i stykker|beskadiget|damaged", re.IGNORECASE), "defekt"),
    (re.compile(r"næsten|naesten|\bsom ny\b|meget god|rigtig god|istandsat", re.IGNORECASE), "naesten_ny"),
    (re.compile(r"\bny\b|\bnyt\b|ny med|ny uden|unused|ubrugt", re.IGNORECASE), "ny"),
    (re.compile(r"tilfredsstillende|rimelig|acceptabelt|\bslidt\b", re.IGNORECASE), "brugt"),
    (re.compile(r"\bgod\b", re.IGNORECASE), "god"),
    (re.compile(r"\bbrugt\b", re.IGNORECASE), "brugt"),
]


def normalize_stand(raw: str) -> str | None:
    """Klassificerer en stand-fritekst (fra ENHVER kilde) til én af de 5
    STAND_TIERS via keyword-heuristik (se _STAND_PATTERNS). Returnerer None
    for tom/'ukendt'/ikke-genkendt formulering -- en ukendt stand skal
    ALDRIG udelukke et match (samme permissive princip som G7s
    stoerrelsesloese oensker), kun en KENDT for-lav stand goer det (se
    _stand_ok)."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    if not s or s == "ukendt":
        return None
    for pattern, tier in _STAND_PATTERNS:
        if pattern.search(s):
            return tier
    return None


def _stand_ok(wl_stand: str, item_stand: str) -> bool:
    """G6: oenskets stand-fritekst er en MINIMUMS-taerskel, ikke et eksakt
    krav -- et 'god'-oenske accepterer ogsaa 'naesten_ny'/'ny'-fund, ikke kun
    praecis 'god'. Returnerer True (blokerer IKKE) medmindre BAADE oenske og
    annonce har en GENKENDT stand og annoncens er strengt vaerre end
    oensket -- ukendt/tom stand paa enten side blokerer aldrig."""
    wl_tier = normalize_stand(wl_stand)
    if wl_tier is None:
        return True  # oensket stiller intet stand-krav
    item_tier = normalize_stand(item_stand)
    if item_tier is None:
        return True  # ukendt annonce-stand -- benefit of the doubt
    return STAND_TIER_RANK[item_tier] <= STAND_TIER_RANK[wl_tier]


def _type_matches(wishlist_type: str, item_title: str) -> bool:
    title_lower = (item_title or "").lower()
    synonyms = TYPE_SYNONYMS.get(wishlist_type, {wishlist_type})
    return any(syn in title_lower for syn in synonyms)


def _neighbor_sizes(size: str) -> set[str]:
    """G15: KUN naeste stoerrelse OP taeller som 'naer' -- ALDRIG en mindre.
    Boern vokser fra toej, ikke ind i det igen -- en annonce der allerede er
    for lille er ubrugelig uanset hvor god en pris/naer-match den ellers
    ville have vaeret. (Foer G15 talte begge naboer -- 104 -> baade 98 og
    110 -- det er den adfaerd Esben eksplicit bad om at fjerne.)"""
    if size not in SIZE_LADDER:
        return set()
    idx = SIZE_LADDER.index(size)
    if idx < len(SIZE_LADDER) - 1:
        return {SIZE_LADDER[idx + 1]}
    return set()


def _item_size_tokens(item_size: str) -> list[str]:
    """G15: Sellpy angiver intervalstoerrelser som "98/104" (bevaret som
    saadan af sources/sellpy.py's _parse_cm_size -- se dens docstring). Vi
    proever HVER stoerrelse i intervallet for sig, saa fx et 98/104-plag
    ogsaa taeller som eksakt/naer for et oenske om 104 (plagget daekker
    rent faktisk den stoerrelse), ikke kun for 98. Almindelige enkelt-
    stoerrelser giver blot en liste med ét element."""
    item_size = str(item_size or "").strip()
    if "/" in item_size:
        return [tok.strip() for tok in item_size.split("/") if tok.strip()]
    return [item_size]


def _size_rank(wl_size: str, item_size: str) -> str | None:
    # G7: oenske UDEN stoerrelse (fx legetoej, boeger, andre boerneting) --
    # stoerrelse er da ikke et matching-kriterie, saa den blokerer ikke og
    # traekker heller ikke ned til "naer match". Tom oenske-stoerrelse
    # matcher enhver (eller ingen) annonce-stoerrelse som "eksakt".
    wl_size = str(wl_size or "").strip()
    if not wl_size:
        return "eksakt"
    best = None
    for tok in _item_size_tokens(item_size):
        if tok == wl_size:
            return "eksakt"
        if tok in _neighbor_sizes(wl_size):
            best = "naer"
    return best


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

    if not _stand_ok(wishlist_item.get("stand", ""), listing.get("stand") or ""):
        return None

    overall_rank = "eksakt" if (size_rank == "eksakt" and brand_rank == "eksakt") else "naer match"

    enriched = dict(listing)
    enriched["match_rank"] = overall_rank
    enriched["wishlist_type"] = wishlist_item["type"]
    enriched["wishlist_maerke"] = wishlist_item.get("maerke", "")
    enriched["wishlist_stoerrelse"] = wishlist_item["stoerrelse"]
    # G6: normaliseret stand vedhaeftes til visning (fx UI/Sheets kan vise et
    # konsistent tier paa tvaers af kilder) -- persisteres IKKE i DB/Turso-
    # skemaet, beregnes on-the-fly hver koersel fra den raa 'stand'.
    enriched["stand_norm"] = normalize_stand(listing.get("stand") or "")
    # G16: synlig advarsel for nedprioriterede saelger-lande (se
    # DEPRIORITIZED_SELLER_COUNTRIES) -- tom streng (ikke None) naar der ikke
    # er noget at advare om, saa UI/Sheets kan bruge feltet direkte uden et
    # separat None-tjek.
    enriched["country_warning"] = (
        COUNTRY_WARNING_TEXT if listing.get("seller_country") in DEPRIORITIZED_SELLER_COUNTRIES else ""
    )
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

    # G16: nedprioriterede saelger-lande (fx polske Vinted-saelgere) sorteres
    # LAENGERE NEDE inden for samme match_rank-tier -- de forbliver synlige
    # (soft, ikke en hard eksklusion), blot ikke foerst i listen.
    rank_order = {"eksakt": 0, "naer match": 1}
    matches.sort(key=lambda m: (
        rank_order.get(m["match_rank"], 2),
        1 if m.get("seller_country") in DEPRIORITIZED_SELLER_COUNTRIES else 0,
        m.get("price", 0),
    ))
    logger.info(
        "Matching: %d match(es) fundet paa tvaers af %d oenskeseddel-item(s) og %d annonce(r)",
        len(matches), len(wishlist), len(listings),
    )
    return matches
