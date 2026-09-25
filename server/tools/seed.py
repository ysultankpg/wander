"""Seed the destinations catalog. Idempotent — safe to run repeatedly."""
from __future__ import annotations

from .store import connect, init_db

DESTINATIONS = [
    ("kyoto", "Kyoto", "Japan", "Asia",
     "Temple city with the best-preserved traditional districts in Japan; peak crowds in cherry blossom and autumn colour seasons.",
     "Mar-Apr, Oct-Nov", 120, "culture,temples,food,walkable"),
    ("lisbon", "Lisbon", "Portugal", "Europe",
     "Hilly Atlantic capital with tiled facades, tram lines and the cheapest big-city food in Western Europe.",
     "Mar-Jun, Sep-Oct", 95, "food,coastal,architecture,nightlife"),
    ("hanoi", "Hanoi", "Vietnam", "Asia",
     "Dense old quarter, street-food culture and the jumping-off point for Ha Long Bay.",
     "Oct-Apr", 45, "food,budget,culture,street-life"),
    ("reykjavik", "Reykjavik", "Iceland", "Europe",
     "Base for glaciers, geysers and the aurora; expensive, but nothing else looks like it.",
     "Sep-Mar aurora, Jun-Aug hiking", 210, "nature,aurora,adventure,hot-springs"),
    ("mexico-city", "Mexico City", "Mexico", "Americas",
     "Vast, green, altitude-2240m capital with world-class museums and the best value fine dining anywhere.",
     "Mar-May, Oct-Nov", 80, "food,museums,culture,nightlife"),
    ("marrakesh", "Marrakesh", "Morocco", "Africa",
     "Walled medina, riad courtyards and souks; a short hop from the High Atlas and the Sahara.",
     "Mar-May, Sep-Nov", 65, "markets,culture,desert,architecture"),
    ("queenstown", "Queenstown", "New Zealand", "Oceania",
     "Adventure-sport capital on Lake Wakatipu — bungee, hiking and ski in one small town.",
     "Dec-Feb hiking, Jun-Aug ski", 155, "adventure,mountains,hiking,ski"),
    ("istanbul", "Istanbul", "Turkey", "Europe",
     "Two continents, Byzantine and Ottoman monuments, and a ferry commute across the Bosphorus.",
     "Apr-Jun, Sep-Nov", 70, "history,food,mosques,markets"),
    ("oaxaca", "Oaxaca", "Mexico", "Americas",
     "Mezcal, mole and Zapotec ruins; the strongest regional food culture in Mexico.",
     "Oct-Apr", 60, "food,crafts,culture,ruins"),
    ("porto", "Porto", "Portugal", "Europe",
     "Port wine lodges across the Douro, azulejo churches and a compact walkable centre.",
     "May-Oct", 85, "wine,food,architecture,river"),
    ("chiang-mai", "Chiang Mai", "Thailand", "Asia",
     "Walled old city of temples, night markets and cooking schools; long-stay favourite.",
     "Nov-Feb", 40, "temples,food,budget,nature"),
    ("ljubljana", "Ljubljana", "Slovenia", "Europe",
     "Small car-free centre with Lake Bled and the Julian Alps within an hour.",
     "May-Sep", 80, "walkable,nature,lakes,budget"),
    ("georgia-tbilisi", "Tbilisi", "Georgia", "Asia",
     "Sulphur baths, 8000-year wine tradition and Caucasus hiking a few hours out.",
     "Apr-Jun, Sep-Oct", 50, "wine,food,mountains,budget"),
    ("cape-town", "Cape Town", "South Africa", "Africa",
     "Table Mountain, Cape winelands and cold-water beaches in one metro area.",
     "Nov-Mar", 90, "nature,wine,beaches,hiking"),
    ("kerala", "Kochi & Kerala Backwaters", "India", "Asia",
     "Colonial-era port, houseboat backwaters and Ayurvedic coast; green and humid.",
     "Oct-Mar", 40, "backwaters,food,budget,coastal"),
    ("seoul", "Seoul", "South Korea", "Asia",
     "Palaces beside 24-hour neighbourhoods; superb public transport and late-night food.",
     "Apr-Jun, Sep-Nov", 100, "food,nightlife,culture,shopping"),
    ("edinburgh", "Edinburgh", "Scotland", "Europe",
     "Volcanic-crag castle, medieval Old Town, and August's festival takeover.",
     "May-Sep", 115, "history,festivals,walkable,whisky"),
    ("medellin", "Medellin", "Colombia", "Americas",
     "Year-round spring climate in an Andean valley; cable-car metro and strong cafe culture.",
     "Dec-Mar, Jul-Aug", 55, "coffee,budget,nightlife,mountains"),
]


def seed() -> int:
    init_db()
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO destinations"
            " (id,name,country,region,summary,best_months,daily_budget_usd,tags)"
            " VALUES (?,?,?,?,?,?,?,?)",
            DESTINATIONS,
        )
        return conn.execute("SELECT COUNT(*) FROM destinations").fetchone()[0]


if __name__ == "__main__":
    print(f"catalog seeded: {seed()} destinations")
