"""Geocoding, weather, and local time — all via keyless Open-Meteo APIs.

No API key, no account, no billing. Open-Meteo is free for non-commercial use
and returns the IANA timezone with geocoding results, which is what makes
worldwide local-time resolution possible without a separate paid service.
"""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

from .http import get_json

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Resolved places are cached for the process lifetime. Coordinates don't change,
# so this both cuts request volume (the biggest cause of shared-IP throttling)
# and lets a place resolve once even if the geocoder is briefly rate-limited.
_PLACE_CACHE: dict[str, dict] = {}

# WMO weather interpretation codes -> plain English.
WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snowfall", 73: "moderate snowfall", 75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


async def resolve_place(place: str) -> dict:
    """Turn a free-text place name into coordinates + timezone.

    Tries Open-Meteo's geocoder first (it returns the IANA timezone directly).
    If that is throttled or finds nothing, falls back to OpenStreetMap's
    Nominatim — a fully independent keyless geocoder — so a rate-limit on one
    provider is not fatal. Successful results are cached for the process life."""
    if not place or not place.strip():
        return {"error": "Please provide a place name."}
    key = place.strip().lower()
    if key in _PLACE_CACHE:
        return _PLACE_CACHE[key]

    resolved = await _resolve_open_meteo(place.strip())
    if "error" in resolved:
        fallback = await _resolve_nominatim(place.strip())
        if "error" not in fallback:
            resolved = fallback
    if "error" not in resolved:
        _PLACE_CACHE[key] = resolved
    return resolved


async def _resolve_open_meteo(place: str) -> dict:
    data = await get_json(GEOCODE_URL, {"name": place, "count": 1, "language": "en"})
    if "error" in data:
        return data
    results = data.get("results") or []
    if not results:
        return {"error": f"Could not find a place called {place!r}."}
    top = results[0]
    label = ", ".join(
        str(p) for p in (top.get("name"), top.get("admin1"), top.get("country")) if p
    )
    return {
        "name": label,
        "latitude": top.get("latitude"),
        "longitude": top.get("longitude"),
        "timezone": top.get("timezone"),
        "country": top.get("country"),
        "population": top.get("population"),
    }


async def _resolve_nominatim(place: str) -> dict:
    """Independent keyless geocoder. Nominatim returns no timezone, but the
    forecast call defaults to timezone=auto, so weather still works; local-time
    lookups backfill the timezone separately when needed."""
    data = await get_json(
        NOMINATIM_URL,
        {"q": place, "format": "json", "limit": 1, "addressdetails": 1},
        headers={"Accept": "application/json"},
    )
    if "error" in data:
        return data
    if not isinstance(data, list) or not data:
        return {"error": f"Could not find a place called {place!r}."}
    top = data[0]
    try:
        lat = float(top.get("lat"))
        lon = float(top.get("lon"))
    except (TypeError, ValueError):
        return {"error": f"Could not resolve coordinates for {place!r}."}
    addr = top.get("address") or {}
    name = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("state") or top.get("display_name", place).split(",")[0])
    label = ", ".join(str(p) for p in (name, addr.get("state"), addr.get("country")) if p)
    return {
        "name": label or place,
        "latitude": lat,
        "longitude": lon,
        "timezone": None,
        "country": addr.get("country"),
        "population": None,
    }


async def get_weather(location: str, forecast_days: int = 3) -> dict:
    """Current conditions plus a short forecast for any place on earth."""
    place = await resolve_place(location)
    if "error" in place:
        return place

    days = max(1, min(int(forecast_days or 3), 7))
    data = await get_json(FORECAST_URL, {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": place.get("timezone") or "auto",
        "forecast_days": days,
    })
    if "error" in data:
        return data

    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    if not cur and not daily:
        # Never let a throttled/partial response look like real weather.
        return {"error": f"Weather data unavailable for {place['name']} right now."}

    forecast = []
    for i, date in enumerate(daily.get("time") or []):
        code = (daily.get("weather_code") or [None])[i]
        forecast.append({
            "date": date,
            "high_c": (daily.get("temperature_2m_max") or [None])[i],
            "low_c": (daily.get("temperature_2m_min") or [None])[i],
            "rain_chance_pct": (daily.get("precipitation_probability_max") or [None])[i],
            "conditions": WMO.get(code, "unknown"),
        })

    return {
        "location": place["name"],
        "current": {
            "temperature_c": cur.get("temperature_2m"),
            "feels_like_c": cur.get("apparent_temperature"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "conditions": WMO.get(cur.get("weather_code"), "unknown"),
        },
        "forecast": forecast,
    }


async def get_local_time(location: str) -> dict:
    """Correct local time and UTC offset for any place, via its IANA timezone."""
    place = await resolve_place(location)
    if "error" in place:
        return place
    tz_name = place.get("timezone")
    if not tz_name:
        # Nominatim path returns no timezone — backfill it from Open-Meteo's
        # forecast API, which echoes the resolved IANA zone for the coordinates.
        tz_name = await _timezone_for(place["latitude"], place["longitude"])
        if tz_name:
            place["timezone"] = tz_name
            _PLACE_CACHE[location.strip().lower()] = place
    if not tz_name:
        return {"error": f"No timezone known for {place['name']}."}
    try:
        now = _dt.datetime.now(ZoneInfo(tz_name))
    except Exception:
        return {"error": f"Unrecognised timezone {tz_name!r}."}

    offset = now.utcoffset() or _dt.timedelta(0)
    total_min = int(offset.total_seconds() // 60)
    sign = "+" if total_min >= 0 else "-"
    return {
        "location": place["name"],
        "timezone": tz_name,
        "local_time": now.strftime("%Y-%m-%d %H:%M"),
        "day_of_week": now.strftime("%A"),
        "utc_offset": f"UTC{sign}{abs(total_min) // 60:02d}:{abs(total_min) % 60:02d}",
    }


async def _timezone_for(lat: float, lon: float) -> str | None:
    """Resolve the IANA timezone for coordinates via Open-Meteo (timezone=auto)."""
    data = await get_json(FORECAST_URL, {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m", "timezone": "auto",
    })
    if "error" in data:
        return None
    return data.get("timezone")
