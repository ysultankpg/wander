"""Live exchange rates and exact conversion via Frankfurter (keyless, ECB data).

Frankfurter needs no key and no Authorization header — sending one (as the
original code did) is at best ignored. Rates are ECB reference rates, published
on working days, so weekend queries return Friday's fixing.
"""
from __future__ import annotations

from .http import get_json

BASE_URL = "https://api.frankfurter.app"


async def get_exchange_rates(base_currency: str = "USD", target_currencies: str = "") -> dict:
    """Latest reference rates for one base against some or all currencies."""
    base = (base_currency or "USD").strip().upper()
    params: dict = {"from": base}
    targets = [c.strip().upper() for c in (target_currencies or "").split(",") if c.strip()]
    if targets:
        params["to"] = ",".join(targets)

    data = await get_json(f"{BASE_URL}/latest", params)
    if "error" in data:
        return data
    if not data.get("rates"):
        return {"error": f"No rates available for base {base!r}."}
    return {"base": data.get("base", base), "as_of": data.get("date"), "rates": data["rates"]}


async def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert a specific amount so trip costs are computed, not estimated."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return {"error": "Amount must be a number."}
    if amt < 0:
        return {"error": "Amount cannot be negative."}

    src = (from_currency or "").strip().upper()
    dst = (to_currency or "").strip().upper()
    if not src or not dst:
        return {"error": "Both from_currency and to_currency are required."}
    if src == dst:
        return {"amount": amt, "from": src, "to": dst, "rate": 1.0, "converted": round(amt, 2)}

    data = await get_json(f"{BASE_URL}/latest", {"from": src, "to": dst})
    if "error" in data:
        return data
    rate = (data.get("rates") or {}).get(dst)
    if rate is None:
        return {"error": f"No rate for {src}->{dst}. Check both currency codes."}

    return {
        "amount": amt,
        "from": src,
        "to": dst,
        "rate": rate,
        "converted": round(amt * float(rate), 2),
        "as_of": data.get("date"),
    }
