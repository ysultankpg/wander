"""Tool registry: JSON schemas advertised to the model, plus dispatch.

user_id is deliberately absent from every schema. The server injects it from the
signed session cookie for the tools that need it, so the model cannot address
another traveller's bookmarks or memories by guessing an id.
"""
from __future__ import annotations

import inspect

from . import geo, images, money, places, store

# Tools whose implementation needs the session-derived user id.
USER_SCOPED = {
    "save_bookmark", "list_bookmarks", "delete_bookmark",
    "remember_preference", "recall_preferences", "forget_preference",
}

SCHEMAS = [
    {"name": "search_destinations",
     "description": "Search the curated destination catalog by region, budget or interest tag. Use this before recommending anywhere.",
     "parameters": {"type": "object", "properties": {
         "region": {"type": "string", "description": "Asia, Europe, Americas, Africa or Oceania"},
         "max_budget_usd": {"type": "integer", "description": "Max daily budget per person in USD"},
         "tag": {"type": "string", "description": "Interest such as food, nature, budget, culture, adventure"},
         "limit": {"type": "integer"}}}},

    {"name": "get_destination",
     "description": "Full catalog detail for one destination id.",
     "parameters": {"type": "object", "properties": {
         "destination_id": {"type": "string"}}, "required": ["destination_id"]}},

    {"name": "get_weather",
     "description": "Real current weather and up to 7 days forecast for any place on earth.",
     "parameters": {"type": "object", "properties": {
         "location": {"type": "string"},
         "forecast_days": {"type": "integer"}}, "required": ["location"]}},

    {"name": "get_local_time",
     "description": "Correct local time, weekday and UTC offset for any place.",
     "parameters": {"type": "object", "properties": {
         "location": {"type": "string"}}, "required": ["location"]}},

    {"name": "find_places",
     "description": "Find real named points of interest near a place from OpenStreetMap.",
     "parameters": {"type": "object", "properties": {
         "location": {"type": "string"},
         "category": {"type": "string", "description": "restaurant, cafe, bar, museum, gallery, attraction, viewpoint, hotel, hostel, park, market, temple, station, beach"},
         "radius_km": {"type": "number"},
         "limit": {"type": "integer"}}, "required": ["location"]}},

    {"name": "get_exchange_rates",
     "description": "Latest ECB reference exchange rates for a base currency.",
     "parameters": {"type": "object", "properties": {
         "base_currency": {"type": "string"},
         "target_currencies": {"type": "string", "description": "Comma separated codes, e.g. JPY,EUR"}}}},

    {"name": "convert_currency",
     "description": "Convert an exact amount between currencies at the live rate. Use for any trip cost maths.",
     "parameters": {"type": "object", "properties": {
         "amount": {"type": "number"},
         "from_currency": {"type": "string"},
         "to_currency": {"type": "string"}},
         "required": ["amount", "from_currency", "to_currency"]}},

    {"name": "get_destination_image",
     "description": "Real photograph of a place from Wikimedia. Call this when showing a destination card.",
     "parameters": {"type": "object", "properties": {
         "place": {"type": "string"}}, "required": ["place"]}},

    {"name": "save_bookmark",
     "description": "Save a trip the traveller wants to keep.",
     "parameters": {"type": "object", "properties": {
         "destination": {"type": "string"},
         "travel_dates": {"type": "string"},
         "notes": {"type": "string"}}, "required": ["destination"]}},

    {"name": "list_bookmarks",
     "description": "List this traveller's saved trips.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},

    {"name": "delete_bookmark",
     "description": "Delete one saved trip by its id.",
     "parameters": {"type": "object", "properties": {
         "bookmark_id": {"type": "integer"}}, "required": ["bookmark_id"]}},

    {"name": "remember_preference",
     "description": "Store a durable traveller preference (diet, allergy, budget, style, avoid).",
     "parameters": {"type": "object", "properties": {
         "kind": {"type": "string", "description": "diet, allergy, budget, style, avoid or interest"},
         "value": {"type": "string"}}, "required": ["kind", "value"]}},

    {"name": "recall_preferences",
     "description": "Retrieve everything known about this traveller.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "forget_preference",
     "description": "Remove a stored preference.",
     "parameters": {"type": "object", "properties": {
         "kind": {"type": "string"}, "value": {"type": "string"}}}},
]

IMPL = {
    "search_destinations": store.search_destinations,
    "get_destination": store.get_destination,
    "get_weather": geo.get_weather,
    "get_local_time": geo.get_local_time,
    "find_places": places.find_places,
    "get_exchange_rates": money.get_exchange_rates,
    "convert_currency": money.convert_currency,
    "get_destination_image": images.get_destination_image,
    "save_bookmark": store.save_bookmark,
    "list_bookmarks": store.list_bookmarks,
    "delete_bookmark": store.delete_bookmark,
    "remember_preference": store.remember,
    "recall_preferences": store.recall,
    "forget_preference": store.forget,
}

# Ollama expects OpenAI-style function tool envelopes.
OLLAMA_TOOLS = [{"type": "function", "function": s} for s in SCHEMAS]


async def call_tool(name: str, args: dict, user_id: str) -> dict:
    """Dispatch one tool call, injecting user_id where the impl requires it."""
    fn = IMPL.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name!r}."}

    kwargs = dict(args or {})
    kwargs.pop("user_id", None)  # never honour a model-supplied identity
    if name in USER_SCOPED:
        kwargs["user_id"] = user_id

    # Drop anything not in the signature so a hallucinated argument can't
    # raise TypeError and abort the turn.
    allowed = set(inspect.signature(fn).parameters)
    kwargs = {k: v for k, v in kwargs.items() if k in allowed}

    try:
        result = fn(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, dict) else {"result": result}
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{name} failed: {type(exc).__name__}"}
