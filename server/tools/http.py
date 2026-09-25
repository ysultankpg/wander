"""One pooled async HTTP client shared by every tool.

Two deliberate choices carried over from the review of the old code:
  * a single pooled AsyncClient instead of per-call clients (connection reuse,
    and no blocking urllib inside an async handler)
  * failures come back as {"error": ...} rather than raising, so a flaky
    third-party API degrades one tool call instead of killing the whole turn.
"""
from __future__ import annotations

import asyncio
import random

import httpx

TIMEOUT = 20.0
_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Wander/1.0 (travel agent; contact via github.com/ysultankpg/wander)"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter: ~0.8, 1.6, 3.2, 6.4s, capped at 8s.

    Free community endpoints (Open-Meteo, Overpass, Nominatim) throttle by IP,
    and shared cloud hosts land on already-hot IPs — so a throttle window needs
    seconds, not milliseconds, to clear. Jitter avoids lock-step retries."""
    return min(8.0, 0.8 * (2 ** attempt)) + random.uniform(0.0, 0.4)


async def get_json(
    url: str,
    params: dict | None = None,
    retries: int = 4,
    headers: dict | None = None,
) -> dict:
    """GET JSON, returning {"error": msg} instead of raising.

    The free community endpoints throttle bursts, so a 429/5xx is retried with
    exponential backoff + jitter. Anything still failing is reported as an
    explicit error — never as a silently empty result, which would let the model
    narrate missing data as if it were real.
    """
    last = "unknown error"
    for attempt in range(retries + 1):
        try:
            resp = await client().get(url, params=params, headers=headers)
            if resp.status_code in (429, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(_backoff(attempt))
                last = f"HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            last = "timeout"
            if attempt < retries:
                await asyncio.sleep(_backoff(attempt))
                continue
            return {"error": "That lookup timed out. Try again in a moment."}
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 429:
                return {"error": "Rate limited by the free weather/map service. Wait a few seconds and retry."}
            return {"error": f"Upstream service returned HTTP {code}."}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Lookup failed: {type(exc).__name__}."}
    return {"error": f"Lookup failed after retries ({last})."}


async def post_text(url: str, data: str, headers: dict | None = None) -> dict:
    """POST a raw body (used for the Overpass OSM query language)."""
    try:
        resp = await client().post(url, content=data, headers=headers or {})
        resp.raise_for_status()
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "That lookup timed out. Try again in a moment."}
    except httpx.HTTPStatusError as exc:
        return {"error": f"Upstream service returned HTTP {exc.response.status_code}."}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Lookup failed: {type(exc).__name__}."}
