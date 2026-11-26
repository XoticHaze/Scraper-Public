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


def scan_coverage(epochs, *, as_of=None):
    """UTC hourly coverage from complete snapshots, not just dates with a scan."""
    valid = sorted({e for e in epochs if isinstance(e, int) and not isinstance(e, bool) and e > 0
                    and (as_of is None or e < as_of)})
    by_day = {}
    for e in valid:
        by_day.setdefault(e // 86400, set()).add((e % 86400) // 3600)
    qualified = sorted(day for day, hours in by_day.items()
                       if len(hours) == 24 and (as_of is None or (day+1)*86400 <= as_of))
    return {"observed_days": len(by_day), "qualified_days": len(qualified),
            "qualified_day_ids": qualified, "observed_hours": sum(len(hours) for hours in by_day.values()),
            "maximum_gap_seconds": max((b-a for a,b in zip(valid,valid[1:])), default=None),
            "latest_scan_epoch_utc": valid[-1] if valid else None,
            "rule": "each UTC hour contains a complete same-scope snapshot; not continuous inventory observation"}


def walk_forward_sold_prices(rows: list[dict[str, Any]], *, complete_scan_epochs: list[int],
                             minimum_samples: int = 20, minimum_days: int = 30) -> dict[str, Any]:
    """Retrospective exact-cohort median hammer forecast, never a probability of sale.

    A prediction at a historical observation timestamp uses only outcomes whose
    close and independent verification both precede it. Complete scan epochs must
    represent the same location/condition/filter scope; daily coverage is necessary,
    not proof that every closing outcome has been reconciled.
    """
    from statistics import median
    def quantile(values, q):
        values = sorted(values)
        x = (len(values)-1)*q
        lo, hi = math.floor(x), math.ceil(x)
        return values[lo] + (values[hi]-values[lo])*(x-lo)
    from bisect import bisect_left
    from collections import defaultdict
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
    by_cohort = defaultdict(list)
    def cohort_key(row):
        return tuple(row.get(k) for k in ("identity", "auction_location", "condition", "scope_id"))
    for key, row in eligible.items():
        by_cohort[cohort_key(row)].append((row["verified_epoch_utc"], key, row))
    for group in by_cohort.values():
        group.sort(key=lambda entry: entry[0])
    index = {key: ([x[0] for x in group], group) for key, group in by_cohort.items()}
    cases = []
    covered_all = set(scan_coverage(complete_scan_epochs)["qualified_day_ids"])
    for key, target in sorted(eligible.items(), key=lambda item: item[1]["prediction_epoch_utc"]):
        cutoff = target["prediction_epoch_utc"]
        cohort = cohort_key(target)
        covered = covered_all
        last_full_day = cutoff // 86400 - 1
        if not all(day in covered for day in range(last_full_day - minimum_days + 1, last_full_day + 1)):
            continue
        timestamps, group = index[cohort]
        prior = [r["final_hammer"] for _, k, r in group[:bisect_left(timestamps, cutoff)]
                 if k != key and r["closed_epoch_utc"] < cutoff
                 and (not target.get("inventory_id") or r.get("inventory_id") != target["inventory_id"])]
        if len(prior) < minimum_samples:
            continue
        predicted = float(median(prior))
        low, high = quantile(prior, .25), quantile(prior, .75)
        observed_hammer = target.get("observed_hammer")
        naive_error = abs(float(observed_hammer) - target["final_hammer"]) if isinstance(observed_hammer, (int, float)) and not isinstance(observed_hammer, bool) and math.isfinite(observed_hammer) and observed_hammer >= 0 else None
        cases.append({"auction_id": key[0], "lot_number": key[1], "prediction_epoch_utc": cutoff,
                      "training_samples": len(prior), "predicted_hammer": predicted,
                      "actual_hammer": target["final_hammer"], "absolute_error": abs(predicted-target["final_hammer"]), "observed_bid_baseline_error": naive_error,
                      "predicted_p25":low,"predicted_p75":high,
                      "inside_p25_p75":low <= target["final_hammer"] <= high})
    paired = [x for x in cases if x["observed_bid_baseline_error"] is not None]
    return {"eligible_outcomes": len(eligible), "evaluated_cases": len(cases),
            "paired_baseline_cases": len(paired),
            "paired_model_mae": round(sum(x["absolute_error"] for x in paired)/len(paired), 2) if paired else None,
            "observed_bid_baseline_mae": round(sum(x["observed_bid_baseline_error"] for x in paired)/len(paired), 2) if paired else None,
            "observed_p25_p75_coverage": round(sum(x["inside_p25_p75"] for x in cases)/len(cases),4) if cases else None,
            "mean_absolute_error": round(sum(x["absolute_error"] for x in cases)/len(cases), 2) if cases else None,
            "cases": cases, "sale_probability": None, "coverage_scope": "caller-supplied same-scope complete scans"}
