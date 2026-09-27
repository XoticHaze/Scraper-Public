from __future__ import annotations

from statistics import mean, median
from typing import Any

SECONDARY_CONDITIONS = {"open_box", "used", "refurbished", "certified_refurbished"}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_money(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def price_stats(observations: list[dict[str, Any]], conditions: set[str]) -> dict[str, Any] | None:
    prices: list[float] = []
    for row in observations:
        condition = str(row.get("condition") or "").strip().lower()
        price = _number(row.get("price"))
        if condition in conditions and price is not None and price > 0:
            prices.append(price)
    if not prices:
        return None
    return {
        "median": _round_money(float(median(prices))),
        "average": _round_money(float(mean(prices))),
        "low": _round_money(min(prices)),
        "high": _round_money(max(prices)),
        "samples": len(prices),
    }


def reverse_max_bid(
    max_all_in: Any,
    *,
    premium_rate: float = 0.15,
    lot_fee: float = 3.0,
    sales_tax_rate: float = 0.0,
) -> float | None:
    """Back an all-in acquisition ceiling into a maximum hammer bid."""
    ceiling = _number(max_all_in)
    if ceiling is None or ceiling <= 0:
        return None
    taxable_subtotal = ceiling / (1.0 + max(0.0, float(sales_tax_rate)))
    bid = (taxable_subtotal - float(lot_fee)) / (1.0 + float(premium_rate))
    return round(max(0.0, bid), 2)


def summarize_market_value(record: dict[str, Any]) -> dict[str, Any]:
    observations = list(record.get("observations") or [])
    current_new = price_stats(observations, {"new"})
    open_box_used = price_stats(observations, SECONDARY_CONDITIONS)
    history = record.get("price_history") if isinstance(record.get("price_history"), dict) else None
    sources = [
        {
            "label": row.get("source_label"),
            "url": row.get("url"),
            "condition": row.get("condition"),
            "price": _number(row.get("price")),
            "observed_at": row.get("observed_at"),
        }
        for row in observations
        if row.get("source_label") and row.get("url")
    ]
    return {
        "status": str(record.get("status") or "verified_external"),
        "identity_confidence": str(record.get("identity_confidence") or "unknown"),
        "price_confidence": str(record.get("price_confidence") or "unknown"),
        "observed_at": record.get("observed_at"),
        "model": record.get("model"),
        "current_new": current_new,
        "open_box_used": open_box_used,
        "price_history": history,
        "source_count": len(sources),
        "sources": sources,
        "allocation_ratio": _number(record.get("allocation_ratio")),
        "risk_note": record.get("risk_note"),
        "specs": record.get("specs") if isinstance(record.get("specs"), dict) else {},
    }


def derive_market_valuation(
    record: dict[str, Any],
    *,
    condition: str,
    current_all_in: Any = None,
    premium_rate: float = 0.15,
    lot_fee: float = 3.0,
    sales_tax_rate: float = 0.0,
    default_allocation_ratio: float = 0.65,
    like_new_fallback_ratio: float = 0.80,
    open_box_fallback_ratio: float = 0.75,
) -> dict[str, Any]:
    """Derive market-backed acquisition ceilings from public external observations.

    MAC.BID stated retail is intentionally not an input. Exact external identity and
    price observations become authoritative when this record is present.
    """
    summary = summarize_market_value(record)
    current_new = summary.get("current_new")
    secondary = summary.get("open_box_used")
    c = (condition or "").strip().upper()

    realistic_open_box = None
    if secondary and secondary.get("median"):
        realistic_open_box = float(secondary["median"])
    elif current_new and current_new.get("median"):
        realistic_open_box = float(current_new["median"]) * open_box_fallback_ratio

    reference_value = realistic_open_box
    reference_basis = "open_box_used_median" if secondary and secondary.get("median") else "new_median_open_box_haircut"

    if c == "LIKE NEW" and not secondary and current_new and current_new.get("median"):
        reference_value = float(current_new["median"]) * like_new_fallback_ratio
        reference_basis = "new_median_like_new_haircut"

    allocation_ratio = _number(record.get("allocation_ratio"))
    if allocation_ratio is None:
        allocation_ratio = default_allocation_ratio
    allocation_ratio = max(0.0, min(1.0, allocation_ratio))

    max_all_in = reference_value * allocation_ratio if reference_value is not None else None
    max_bid = reverse_max_bid(
        max_all_in,
        premium_rate=premium_rate,
        lot_fee=lot_fee,
        sales_tax_rate=sales_tax_rate,
    )

    all_in = _number(current_all_in)
    discount_pct = None
    savings = None
    if reference_value and all_in is not None:
        discount_pct = (1.0 - all_in / reference_value) * 100.0
        savings = reference_value - all_in

    return {
        "market_price_status": "verified_external",
        "market_value_confidence": summary.get("price_confidence"),
        "market_identity_confidence": summary.get("identity_confidence"),
        "market_value_observed_at": summary.get("observed_at"),
        "market_value_source_count": summary.get("source_count"),
        "verified_new_price": current_new.get("median") if current_new else None,
        "current_new_average": current_new.get("average") if current_new else None,
        "current_new_low": current_new.get("low") if current_new else None,
        "current_new_high": current_new.get("high") if current_new else None,
        "current_new_samples": current_new.get("samples") if current_new else None,
        "realistic_open_box_value": _round_money(realistic_open_box),
        "market_reference_value": _round_money(reference_value),
        "market_reference_basis": reference_basis if reference_value is not None else None,
        "allocation_ratio": round(allocation_ratio, 4),
        "max_all_in": _round_money(max_all_in),
        "verified_max_bid": max_bid,
        "max_bid": max_bid,
        "verified_discount_pct": round(discount_pct, 1) if discount_pct is not None else None,
        "verified_savings": _round_money(savings),
    }
