"""Live verification of every keyless tool. Run: python -m server.verify"""
import asyncio
import json

from server.tools import geo, images, money, places, registry, seed, store


async def main() -> None:
    print(f"catalog: {seed.seed()} destinations seeded\n")

    w = await geo.get_weather("Kyoto, Japan", 3)
    print("WEATHER Kyoto:", w.get("current"), "| days:", len(w.get("forecast", [])))
    for city in ("Reykjavik", "Singapore"):
        c = (await geo.get_weather(city, 1)).get("current", {})
        print(f"  {city}: {c.get('temperature_c')}C {c.get('conditions')}")

    for city in ("Tokyo", "Hyderabad, India", "Reykjavik"):
        t = await geo.get_local_time(city)
        print(f"TIME {city}: {t.get('local_time')} {t.get('timezone')} {t.get('utc_offset')}")

    p = await places.find_places("Kyoto, Japan", "temple", 3, 4)
    print("OSM temples:", [x["name"] for x in p.get("places", [])])
    r = await places.find_places("Lisbon, Portugal", "cafe", 2, 3)
    print("OSM cafes:", [x["name"] for x in r.get("places", [])])

    fx = await money.convert_currency(1500, "USD", "JPY")
    print("FX 1500 USD->JPY:", fx.get("converted"), "@", fx.get("rate"))

    img = await images.get_destination_image("Kyoto")
    print("IMAGE:", (img.get("image_url") or img.get("error", ""))[:78])

    d = store.search_destinations(region="Asia", max_budget_usd=60, limit=3)
    print("CATALOG Asia<=60:", [x["name"] for x in d["destinations"]])

    uid = "verify-user"
    store.remember(uid, "allergy", "peanuts")
    store.remember(uid, "diet", "vegetarian")
    print("MEMORY:", store.recall(uid)["memories"])
    bm = store.save_bookmark(uid, "Kyoto", "March 2027", "cherry blossom")
    print("BOOKMARK saved id:", bm.get("bookmark_id"))
    print("OWNERSHIP enforced:", store.delete_bookmark("other-user", bm["bookmark_id"]))
    store.delete_bookmark(uid, bm["bookmark_id"])
    store.forget(uid)

    print("\nERROR HANDLING")
    print("  empty place:", "error" in await geo.get_weather(""))
    print("  nonsense place:", "error" in await geo.get_local_time("Qwertyuiop Nowhere"))
    print("  bad currency:", "error" in await money.convert_currency(10, "USD", "XYZ"))
    print("  bad category:", "error" in await places.find_places("Paris", "spaceport"))
    print("  unknown tool:", await registry.call_tool("no_such_tool", {}, uid))
    print("  injected user_id ignored:",
          (await registry.call_tool("recall_preferences", {"user_id": "attacker"}, uid)))

    print(f"\ntools advertised to model: {len(registry.SCHEMAS)}")
    await geo.get_json.__globals__["aclose"]() if False else None
    from server.tools import http
    await http.aclose()


asyncio.run(main())
