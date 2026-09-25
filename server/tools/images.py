"""Real destination photos from Wikimedia Commons (keyless).

Replaces generated imagery on Cloud Storage. Two honest properties:
  * these are real photographs, not model output, so nothing is fabricated
  * when no image exists we say so instead of returning a broken URL — the old
    code uploaded a 44-byte fake MP4 and reported success, which is worse than
    a plain failure because it looks like it worked.
"""
from __future__ import annotations

from .http import get_json

API = "https://en.wikipedia.org/w/api.php"


async def get_destination_image(place: str, width: int = 900) -> dict:
    """Lead photograph for a place, straight from its Wikipedia article."""
    if not place or not place.strip():
        return {"error": "Please provide a place name."}

    px = max(320, min(int(width or 900), 1600))
    data = await get_json(API, {
        "action": "query",
        "format": "json",
        "prop": "pageimages|info",
        "inprop": "url",
        "piprop": "thumbnail",
        "pithumbsize": px,
        "generator": "search",
        "gsrsearch": place.strip(),
        "gsrlimit": 1,
        "origin": "*",
    })
    if "error" in data:
        return data

    pages = ((data.get("query") or {}).get("pages") or {})
    for page in pages.values():
        thumb = (page.get("thumbnail") or {}).get("source")
        if thumb:
            return {
                "place": place.strip(),
                "title": page.get("title"),
                "image_url": thumb,
                "article_url": page.get("fullurl"),
                "credit": "Wikimedia Commons / Wikipedia",
            }
    return {"error": f"No photograph found for {place!r} on Wikimedia."}
