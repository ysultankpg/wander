"""Points of interest from OpenStreetMap via the Overpass API (keyless).

Replaces the Google Places API, which needs a billed key. Overpass is a free
community endpoint, so we keep queries small and specific: a bounded radius,
a capped result count, and a short server-side timeout.
"""
from __future__ import annotations

from .geo import resolve_place
from .http import post_text

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Friendly category -> OSM tag filters.
CATEGORIES = {
    "restaurant": '["amenity"="restaurant"]',
    "cafe": '["amenity"="cafe"]',
    "bar": '["amenity"="bar"]',
    "museum": '["tourism"="museum"]',
    "gallery": '["tourism"="gallery"]',
    "attraction": '["tourism"="attraction"]',
    "viewpoint": '["tourism"="viewpoint"]',
    "hotel": '["tourism"="hotel"]',
    "hostel": '["tourism"="hostel"]',
    "park": '["leisure"="park"]',
    "market": '["amenity"="marketplace"]',
    "temple": '["amenity"="place_of_worship"]',
    "station": '["railway"="station"]',
    "beach": '["natural"="beach"]',
}


async def find_places(
    location: str,
    category: str = "attraction",
    radius_km: float = 3.0,
    limit: int = 8,
) -> dict:
    """Find nearby points of interest in one category around a place."""
    cat = (category or "attraction").strip().lower()
    if cat not in CATEGORIES:
        return {
            "error": f"Unknown category {cat!r}.",
            "supported": sorted(CATEGORIES),
        }

    place = await resolve_place(location)
    if "error" in place:
        return place

    radius_m = int(max(0.2, min(float(radius_km or 3.0), 20.0)) * 1000)
    cap = max(1, min(int(limit or 8), 20))
    tag = CATEGORIES[cat]
    lat, lon = place["latitude"], place["longitude"]

    # [out:json] gives JSON; nwr matches nodes/ways/relations; center gives a
    # single coordinate for ways so every result has a usable lat/lon.
    query = (
        f"[out:json][timeout:20];"
        f"nwr{tag}(around:{radius_m},{lat},{lon});"
        f"out center {cap * 3};"
    )
    data = await post_text(OVERPASS_URL, query, {"Content-Type": "text/plain"})
    if "error" in data:
        return data

    seen: set[str] = set()
    places: list[dict] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name or name in seen:
            continue  # unnamed OSM features are noise for a traveller
        seen.add(name)
        places.append({
            "name": name,
            "category": cat,
            "cuisine": tags.get("cuisine"),
            "address": tags.get("addr:street"),
            "website": tags.get("website") or tags.get("contact:website"),
            "opening_hours": tags.get("opening_hours"),
            "latitude": el.get("lat") or (el.get("center") or {}).get("lat"),
            "longitude": el.get("lon") or (el.get("center") or {}).get("lon"),
        })
        if len(places) >= cap:
            break

    if not places:
        return {
            "location": place["name"],
            "category": cat,
            "places": [],
            "note": f"No named {cat} entries in OpenStreetMap within {radius_km}km.",
        }
    return {"location": place["name"], "category": cat, "count": len(places), "places": places}
