from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.replace("$", "").replace(",", "").strip()
        try:
            return float(text)
        except ValueError:
            return None
    return None


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first non-None value, preserving valid zero values."""
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def estimated_pre_tax_total(current_bid: Any, premium_rate: float = 0.15, lot_fee: float = 3.0) -> float | None:
    bid = number(current_bid)
    if bid is None or bid < 0:
        return None
    return round(bid * (1.0 + premium_rate) + lot_fee, 2)


def estimated_post_tax_total(
    current_bid: Any,
    premium_rate: float = 0.15,
    lot_fee: float = 3.0,
    sales_tax_rate: float = 0.0,
) -> tuple[float | None, float | None]:
    subtotal = estimated_pre_tax_total(current_bid, premium_rate=premium_rate, lot_fee=lot_fee)
    if subtotal is None:
        return None, None
    tax = round(subtotal * max(0.0, float(sales_tax_rate)), 2)
    return tax, round(subtotal + tax, 2)


def provisional_max_bid(
    retail_price: Any,
    condition: str,
    premium_rate: float = 0.15,
    lot_fee: float = 3.0,
    sales_tax_rate: float = 0.0,
    like_new_ratio: float = 0.35,
    open_box_ratio: float = 0.25,
) -> float | None:
    """Preliminary hammer ceiling derived only from MAC.BID's stated retail.

    The target ratio is treated as an all-in ceiling. Sales tax is therefore
    backed out before buyer premium and lot fee are inverted. This is still
    deliberately provisional until exact model and real market price are verified.
    """
    retail = number(retail_price)
    if retail is None or retail <= 0:
        return None
    c = (condition or "").strip().upper()
    ratio = like_new_ratio if c == "LIKE NEW" else open_box_ratio
    target_all_in = retail * ratio
    taxable_subtotal_ceiling = target_all_in / (1.0 + max(0.0, float(sales_tax_rate)))
    bid = (taxable_subtotal_ceiling - lot_fee) / (1.0 + premium_rate)
    return round(max(0.0, bid), 2)


def parse_close(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        # MAC.BID's public Typesense expected_close_date is a calendar date only.
        # Do not invent midnight as an exact close time; enrichment handles that.
        if DATE_ONLY_RE.fullmatch(raw):
            return None
        text = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def hours_until_close(value: Any, now: datetime | None = None) -> float | None:
    close = parse_close(value)
    if close is None:
        return None
    current = now or datetime.now(timezone.utc)
    return (close - current).total_seconds() / 3600.0


def score_lot(
    lot: dict[str, Any],
    *,
    premium_rate: float = 0.15,
    lot_fee: float = 3.0,
    sales_tax_rate: float = 0.0,
    low_value_retail_floor: float = 40.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    condition = str(lot.get("condition") or "").strip().upper()
    retail = number(first_present(lot, "retail_price", "retail"))
    bid = number(first_present(lot, "current_bid", "current_price", "price"))
    pre_tax_total = estimated_pre_tax_total(bid, premium_rate=premium_rate, lot_fee=lot_fee)
    estimated_tax, all_in_total = estimated_post_tax_total(
        bid,
        premium_rate=premium_rate,
        lot_fee=lot_fee,
        sales_tax_rate=sales_tax_rate,
    )
    bidders = int(number(lot.get("unique_bidders")) or 0)
    bids = int(number(lot.get("total_bids")) or 0)
    close_value = first_present(lot, "live_close_time", "end_time", "closing_date", "expected_close_date")
    hours = hours_until_close(close_value, now=now)

    score = 0.0
    reasons: list[str] = []

    if condition == "LIKE NEW":
        score += 16
        reasons.append("like-new condition")
    elif condition == "OPEN BOX":
        score += 8
        reasons.append("open-box condition")
    else:
        score -= 25
        reasons.append("non-preferred condition")

    discount_pct = None
    savings = None
    comparison_total = all_in_total if all_in_total is not None else pre_tax_total
    if retail is not None and retail > 0 and comparison_total is not None:
        discount_pct = max(-1.0, min(1.0, 1.0 - (comparison_total / retail)))
        savings = retail - comparison_total
        score += max(-20.0, min(42.0, discount_pct * 48.0))
        if savings > 0:
            score += min(24.0, math.log1p(savings) * 4.0)
        if retail < low_value_retail_floor:
            score -= 12.0
            reasons.append("low stated retail")
        if discount_pct >= 0.70:
            reasons.append("70%+ below stated retail estimated all-in")
        elif discount_pct >= 0.50:
            reasons.append("50%+ below stated retail estimated all-in")
    else:
        score -= 8.0
        reasons.append("missing usable retail/current bid")

    if bidders == 0:
        score += 10
        reasons.append("no bidders yet")
    elif bidders == 1:
        score += 8
        reasons.append("one bidder")
    elif bidders <= 3:
        score += 5
    elif bidders >= 8:
        score -= 5
        reasons.append("high bidder competition")

    if bids >= 20:
        score -= 4

    # Exact urgency only applies after an exact live close time is available.
    if hours is not None:
        if 0 <= hours <= 6:
            score += 5
            reasons.append("closes within 6h")
        elif 0 <= hours <= 24:
            score += 3
            reasons.append("closes within 24h")
        elif hours < 0:
            score -= 50

    ceiling = provisional_max_bid(
        retail,
        condition,
        premium_rate=premium_rate,
        lot_fee=lot_fee,
        sales_tax_rate=sales_tax_rate,
    )

    return {
        "deal_score": round(score, 2),
        "estimated_pre_tax_total": pre_tax_total,
        "estimated_sales_tax": estimated_tax,
        "estimated_post_tax_total": all_in_total,
        "estimated_all_in_total": all_in_total,
        "sales_tax_rate": round(float(sales_tax_rate), 6),
        "stated_retail": retail,
        "stated_retail_discount_pct": round(discount_pct * 100.0, 1) if discount_pct is not None else None,
        "stated_retail_savings": round(savings, 2) if savings is not None else None,
        "hours_until_close": round(hours, 2) if hours is not None else None,
        "provisional_max_bid": ceiling,
        "provisional_ceiling_basis": "MAC.BID stated retail only; estimated tax included; verify exact model and real market price before bidding",
        "reasons": reasons,
    }
