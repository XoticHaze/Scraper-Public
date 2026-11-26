"""Offline analysis of explicitly evidenced public auction outcomes.

No network, account state, live scoring changes, or inferred sales.
"""
from __future__ import annotations

import math
from typing import Any

from deal_engine.scoring import estimated_post_tax_total


def summarize_outcomes(rows: list[dict[str, Any]], *, budget: float,
                       premium_rate: float, lot_fee: float, sales_tax_rate: float) -> dict[str, Any]:
    """Descriptive statistics only; caller selects a comparable cohort.

    Search-discovered samples cannot establish arrival rates, market-wide
    probability, or waiting time. Cost uses an explicit fee scenario.
    """
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("auction_id") or ""), str(row.get("lot_number") or ""))
        if not all(key):
            raise ValueError("missing stable auction/lot identity")
        if key in unique and unique[key] != row:
            raise ValueError("conflicting duplicate outcome")
        unique[key] = row
    prices = []
    unsold = unresolved = 0
    for row in unique.values():
        status = row.get("status")
        hammer = row.get("final_hammer")
        if status in ("closed_sold_verified", "closed_unsold_verified"):
            if not str(row.get("source_url") or "").startswith("https://www.mac.bid/"):
                raise ValueError("missing official source")
        if status == "closed_sold_verified":
            if isinstance(hammer, bool) or not isinstance(hammer, (int, float)) or not math.isfinite(hammer) or hammer <= 0:
                raise ValueError("invalid verified hammer")
            _, total = estimated_post_tax_total(hammer, premium_rate=premium_rate,
                lot_fee=lot_fee, sales_tax_rate=sales_tax_rate)
            prices.append(total)
        elif status == "closed_unsold_verified":
            if hammer is not None:
                raise ValueError("unsold record must not contain a hammer")
            unsold += 1
        else:
            unresolved += 1
    prices.sort()
    def percentile(q: float) -> float | None:
        if not prices:
            return None
        i = (len(prices) - 1) * q
        lo, hi = math.floor(i), math.ceil(i)
        return round(prices[lo] + (prices[hi] - prices[lo]) * (i - lo), 2)
    return {
        "sample_lots": len(unique), "verified_sold": len(prices),
        "verified_unsold": unsold, "unresolved": unresolved,
        "estimated_all_in_p25": percentile(.25), "estimated_all_in_p50": percentile(.5),
        "estimated_all_in_p75": percentile(.75), "estimated_all_in_p90": percentile(.9),
        "observed_sold_at_or_below_budget": sum(p <= budget for p in prices),
        "budget": budget, "fee_scenario": {"premium_rate": premium_rate,
            "lot_fee": lot_fee, "sales_tax_rate": sales_tax_rate},
        "market_probability": None, "expected_wait": None,
        "coverage": "not established; descriptive sample only",
    }
