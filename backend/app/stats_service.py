"""Trip-history stats, computed at read time from existing Trip rows --
no new write path, no drift risk (CLAUDE.md principle #2/#7: derive from
real data, never a separate counter that can fall out of sync with it).
Backs both the gamification passport (routers/gamification.py) and
achievement-threshold checks (gamification_service.py).
"""
from sqlalchemy.orm import Session

from . import models

# Trip.destination is free text (e.g. "Paris", "a week in Kyoto") with no
# country field anywhere in the schema, and there's no budget for a
# geocoding API call just to infer one (CLAUDE.md: $0 unless told
# otherwise). This is a deliberately small, non-exhaustive substring
# lookup, not an attempt at real geocoding:
#   - It only recognizes a destination whose text contains one of these
#     keys -- "a small town in Provence" won't match "France" unless a
#     known French city/keyword is in the destination text.
#   - It silently UNDERCOUNTS unrecognized destinations; it never
#     overcounts or guesses (CLAUDE.md principle #7 -- no data beats
#     invented data).
#   - No disambiguation for ambiguous names (e.g. "Georgia" the US state
#     vs. the country) -- biased toward the common/likely reading rather
#     than solved.
CITY_OR_KEYWORD_TO_COUNTRY: dict[str, str] = {
    "paris": "France", "france": "France", "nice": "France", "lyon": "France",
    "london": "United Kingdom", "england": "United Kingdom", "scotland": "United Kingdom",
    "edinburgh": "United Kingdom", "manchester": "United Kingdom",
    "rome": "Italy", "italy": "Italy", "venice": "Italy", "florence": "Italy", "milan": "Italy",
    "madrid": "Spain", "spain": "Spain", "barcelona": "Spain", "seville": "Spain",
    "lisbon": "Portugal", "portugal": "Portugal", "porto": "Portugal",
    "berlin": "Germany", "germany": "Germany", "munich": "Germany",
    "amsterdam": "Netherlands", "netherlands": "Netherlands",
    "athens": "Greece", "greece": "Greece", "santorini": "Greece",
    "dublin": "Ireland", "ireland": "Ireland",
    "zurich": "Switzerland", "switzerland": "Switzerland", "geneva": "Switzerland",
    "vienna": "Austria", "austria": "Austria",
    "prague": "Czech Republic",
    "istanbul": "Turkey", "turkey": "Turkey",
    "reykjavik": "Iceland", "iceland": "Iceland",
    "tokyo": "Japan", "japan": "Japan", "kyoto": "Japan", "osaka": "Japan",
    "seoul": "South Korea", "korea": "South Korea",
    "beijing": "China", "shanghai": "China",
    "bangkok": "Thailand", "thailand": "Thailand", "phuket": "Thailand",
    "bali": "Indonesia", "indonesia": "Indonesia", "jakarta": "Indonesia",
    "singapore": "Singapore",
    "hanoi": "Vietnam", "vietnam": "Vietnam",
    "mumbai": "India", "delhi": "India", "india": "India", "goa": "India",
    "dubai": "United Arab Emirates",
    "sydney": "Australia", "australia": "Australia", "melbourne": "Australia",
    "auckland": "New Zealand", "new zealand": "New Zealand",
    "cairo": "Egypt", "egypt": "Egypt",
    "cape town": "South Africa", "south africa": "South Africa",
    "marrakech": "Morocco", "morocco": "Morocco",
    "nairobi": "Kenya", "kenya": "Kenya",
    "mexico city": "Mexico", "cancun": "Mexico", "mexico": "Mexico",
    "rio de janeiro": "Brazil", "brazil": "Brazil", "sao paulo": "Brazil",
    "buenos aires": "Argentina", "argentina": "Argentina",
    "lima": "Peru", "peru": "Peru", "machu picchu": "Peru",
    "toronto": "Canada", "vancouver": "Canada", "canada": "Canada", "montreal": "Canada",
    "new york": "United States", "los angeles": "United States", "chicago": "United States",
    "san francisco": "United States", "miami": "United States", "austin": "United States",
    "seattle": "United States", "boston": "United States", "usa": "United States",
    "united states": "United States",
}


def infer_country(destination: str) -> str | None:
    """Case-insensitive substring match against CITY_OR_KEYWORD_TO_COUNTRY.
    None (never a guess) for anything unrecognized."""
    if not destination:
        return None
    lowered = destination.lower()
    for keyword, country in CITY_OR_KEYWORD_TO_COUNTRY.items():
        if keyword in lowered:
            return country
    return None


def compute_trip_stats(user_id: int, db: Session) -> dict:
    """Small, flat dict (CLAUDE.md principle #2) built from a live query
    over this user's Trip rows -- {"trip_count", "distinct_destinations",
    "countries_visited", "country_count"}. Excludes edit_trip-regenerated
    rows (Trip.is_edit) so a conversational "make it more relaxed" doesn't
    inflate trip counts, badges, or passport stamps the way it would if
    every regeneration counted as a separately-planned trip -- see
    routers/trips.py's new_trip/edit_trip branching, which is what sets
    is_edit at creation time.
    """
    trips = (
        db.query(models.Trip)
        .filter(models.Trip.user_id == user_id, models.Trip.is_edit.is_(False))
        .all()
    )

    destinations = {t.destination for t in trips if t.destination}
    countries = {infer_country(t.destination) for t in trips if t.destination}
    countries.discard(None)

    return {
        "trip_count": len(trips),
        "distinct_destinations": len(destinations),
        "countries_visited": sorted(countries),
        "country_count": len(countries),
    }
