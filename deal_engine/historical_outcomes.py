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


def walk_forward_sold_prices(rows: list[dict[str, Any]], *, complete_scan_epochs: list[int],
                             minimum_samples: int = 20, minimum_days: int = 30) -> dict[str, Any]:
    """Retrospective exact-cohort median hammer forecast, never a probability of sale.

    A prediction at a historical observation timestamp uses only outcomes whose
    close and independent verification both precede it. Complete scan epochs must
    represent the same location/condition/filter scope; daily coverage is necessary,
    not proof that every closing outcome has been reconciled.
    """
    from statistics import median
    if minimum_samples < 20 or minimum_days < 30:
        raise ValueError("minimum evidence thresholds cannot be weakened")
    def epoch(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    eligible = {}
    for row in rows:
        if row.get("training_eligible") is not True or row.get("status") != "closed_sold_verified":
            continue
        if row.get("reconciliation_level") != "lot_detail_reconciled":
            continue
        key = tuple(str(row.get(k) or "") for k in ("auction_id", "lot_number"))
        cohort = tuple(str(row.get(k) or "") for k in ("identity", "auction_location", "condition"))
        closed, known, observed = (epoch(row.get(k)) for k in ("closed_epoch_utc", "verified_epoch_utc", "prediction_epoch_utc"))
        hammer = row.get("final_hammer")
        if (not all(key) or not all(cohort) or not (observed and closed and known and observed < closed <= known)
                or not isinstance(hammer, (int, float)) or isinstance(hammer, bool)
                or not math.isfinite(hammer) or hammer <= 0
                or not str(row.get("source_url") or "").startswith("https://www.mac.bid/")):
            continue
        if key in eligible and eligible[key] != row:
            raise ValueError("conflicting duplicate outcome")
        eligible[key] = row
    cases = []
    for key, target in sorted(eligible.items(), key=lambda item: item[1]["prediction_epoch_utc"]):
        cutoff = target["prediction_epoch_utc"]
        cohort = tuple(target[k] for k in ("identity", "auction_location", "condition"))
        covered = {e // 86400 for e in complete_scan_epochs if epoch(e) and e < cutoff}
        last_full_day = cutoff // 86400 - 1
        if not all(day in covered for day in range(last_full_day - minimum_days + 1, last_full_day + 1)):
            continue
        prior = [r["final_hammer"] for k, r in eligible.items()
                 if k != key and tuple(r[f] for f in ("identity", "auction_location", "condition")) == cohort
                 and r["verified_epoch_utc"] < cutoff and r["closed_epoch_utc"] < cutoff
                 and (not target.get("inventory_id") or r.get("inventory_id") != target["inventory_id"])]
        if len(prior) < minimum_samples:
            continue
        predicted = float(median(prior))
        cases.append({"auction_id": key[0], "lot_number": key[1], "prediction_epoch_utc": cutoff,
                      "training_samples": len(prior), "predicted_hammer": predicted,
                      "actual_hammer": target["final_hammer"], "absolute_error": abs(predicted-target["final_hammer"])})
    return {"eligible_outcomes": len(eligible), "evaluated_cases": len(cases),
            "mean_absolute_error": round(sum(x["absolute_error"] for x in cases)/len(cases), 2) if cases else None,
            "cases": cases, "sale_probability": None, "coverage_scope": "caller-supplied same-scope complete scans"}
