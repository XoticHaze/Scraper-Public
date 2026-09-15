from __future__ import annotations

import re
from typing import Any


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _trim_key(row: dict[str, Any]) -> str:
    trim = _norm(row.get("trim"))
    if trim:
        return " ".join(trim.split()[:3])
    title = _norm(row.get("title"))
    marker = "rav4 "
    if marker in title:
        return " ".join(title.split(marker, 1)[1].split()[:3])
    return title


def signature(row: dict[str, Any]) -> str:
    vin = _norm(row.get("vin"))
    if len(vin) == 17:
        return f"vin:{vin}"
    return "|".join((
        str(int(row.get("year") or 0)),
        _trim_key(row),
        str(int(row.get("mileage") or -1)),
        _norm(row.get("dealer")),
    ))


def market_signature(row: dict[str, Any]) -> str:
    """Conservative fallback for dealer-direct vs aggregator copies without VIN.

    Require exact year, trim, mileage, price, and normalized dealer identity.
    VIN remains the preferred cross-source identity whenever available.
    """
    return "|".join((
        str(int(row.get("year") or 0)),
        _trim_key(row),
        str(int(row.get("mileage") or -1)),
        str(int(float(row.get("price") or -1))),
        _norm(row.get("dealer")),
    ))


def _quality(row: dict[str, Any]) -> tuple[int, int, int]:
    kind = str(row.get("source_kind") or "")
    direct = 1 if kind == "direct_dealer" else 0
    completeness = sum(bool(row.get(key)) for key in (
        "vin", "dealer", "drivetrain", "image_url", "stock_number", "transmission",
    ))
    return direct, completeness, -len(str(row.get("source_url") or ""))


def _merge(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    out = dict(primary)
    urls = []
    for value in (
        *(out.get("alternate_urls") or []), out.get("source_url"),
        *(duplicate.get("alternate_urls") or []), duplicate.get("source_url"),
    ):
        if value and value not in urls:
            urls.append(value)
    sources = []
    for value in (
        *(out.get("sources") or []), out.get("source"),
        *(duplicate.get("sources") or []), duplicate.get("source"),
    ):
        if value and value not in sources:
            sources.append(value)
    observed_prices = []
    for value in (
        *(out.get("observed_prices") or []), out.get("price"),
        *(duplicate.get("observed_prices") or []), duplicate.get("price"),
    ):
        if isinstance(value, (int, float)) and value not in observed_prices:
            observed_prices.append(value)
    out["alternate_urls"] = urls
    out["sources"] = sources
    out["observed_prices"] = sorted(observed_prices)
    for key in (
        "vin", "dealer", "drivetrain", "image_url", "stock_number", "transmission",
        "fuel_type", "distance_miles", "location", "area_priority", "locality_hint",
        "dealer_doc_fee", "dealer_doc_fee_included_in_price", "dealer_addon_warning",
    ):
        if out.get(key) in (None, "", False) and duplicate.get(key) not in (None, ""):
            out[key] = duplicate[key]
    return out


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse cross-source copies, preferring dealer-direct authoritative rows."""
    chosen: list[dict[str, Any]] = []
    by_vin: dict[str, int] = {}
    by_market: dict[str, int] = {}

    for row in rows:
        vin = _norm(row.get("vin"))
        mkey = market_signature(row)
        idx = by_vin.get(vin) if len(vin) == 17 else None
        if idx is None:
            idx = by_market.get(mkey)
        if idx is None:
            idx = len(chosen)
            chosen.append(dict(row))
        else:
            existing = chosen[idx]
            if _quality(row) > _quality(existing):
                chosen[idx] = _merge(dict(row), existing)
            else:
                chosen[idx] = _merge(existing, row)
        current = chosen[idx]
        current_vin = _norm(current.get("vin"))
        if len(current_vin) == 17:
            by_vin[current_vin] = idx
        by_market[market_signature(current)] = idx

    return chosen
