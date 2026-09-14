from __future__ import annotations

import statistics
from typing import Any


def estimate_otd(price: float, policy: dict[str, Any]) -> float:
    tax = float(policy.get("sales_tax_rate", 0.0625))
    title_reg = float(policy.get("estimated_title_registration", 250.0))
    doc = float(policy.get("assumed_doc_fee", 225.0))
    return round(price * (1.0 + tax) + title_reg + doc, 2)


def locality_bucket(distance_miles: int | None, policy: dict[str, Any], market_local: bool = False) -> str:
    if market_local:
        return "local"
    if distance_miles is None:
        return "unknown"
    preferred = int(policy.get("preferred_radius_miles", 50))
    hard = int(policy.get("hard_radius_miles", 200))
    if distance_miles <= 25:
        return "local"
    if distance_miles <= preferred:
        return "nearby"
    if distance_miles <= hard:
        return "regional"
    return "out_of_scope"


def eligible(row: dict[str, Any], policy: dict[str, Any]) -> bool:
    if int(row.get("year") or 0) < int(policy.get("year_min", 2018)):
        return False
    if int(row.get("year") or 9999) > int(policy.get("year_max", 2025)):
        return False
    if float(row.get("price") or 1e18) > float(policy.get("max_price", 27000)):
        return False
    if int(row.get("mileage") or 10**9) > int(policy.get("max_mileage", 100000)):
        return False
    distance = row.get("distance_miles")
    if distance is not None and int(distance) > int(policy.get("hard_radius_miles", 200)):
        return False
    return True


def _comp_median(row: dict[str, Any], universe: list[dict[str, Any]]) -> float | None:
    year = int(row.get("year") or 0)
    drive = str(row.get("drivetrain") or "").lower()
    candidates = [
        float(other["price"])
        for other in universe
        if other is not row
        and other.get("price") is not None
        and abs(int(other.get("year") or 0) - year) <= 1
        and (not drive or str(other.get("drivetrain") or "").lower() == drive)
    ]
    if len(candidates) < 3:
        candidates = [
            float(other["price"])
            for other in universe
            if other is not row and other.get("price") is not None and abs(int(other.get("year") or 0) - year) <= 1
        ]
    return statistics.median(candidates) if candidates else None


def score_vehicle(row: dict[str, Any], policy: dict[str, Any], universe: list[dict[str, Any]]) -> dict[str, Any]:
    price = float(row["price"])
    mileage = int(row["mileage"])
    year = int(row["year"])
    target_price = float(policy.get("target_price", 23000))
    preferred_mileage = int(policy.get("preferred_mileage", 45000))
    maintenance_control = int(policy.get("maintenance_control_mileage", 35000))
    distance = row.get("distance_miles")

    score = 50.0
    reasons: list[str] = []
    risks: list[str] = []

    score += max(-18.0, min(22.0, (target_price - price) / 250.0))
    if price <= target_price:
        reasons.append("at_or_below_target_price")

    if mileage <= maintenance_control:
        score += 18.0
        reasons.append("maintenance_history_can_be_taken_over_early")
    elif mileage <= preferred_mileage:
        score += 10.0
        reasons.append("low_mileage")
    elif mileage <= 60000:
        score += 3.0
    else:
        score -= min(24.0, (mileage - 60000) / 2500.0)
        risks.append("past_60k_service_ambiguity")

    score += max(0.0, min(10.0, (year - 2018) * 1.4))

    drive = str(row.get("drivetrain") or "").lower()
    if "all-wheel" in drive or "awd" in drive:
        score += 6.0
        reasons.append("awd_colorado_trip_capability")
    elif "front-wheel" in drive or "fwd" in drive:
        reasons.append("simpler_fwd_driveline")

    bucket = locality_bucket(distance, policy, bool(row.get("market_local")))
    if bucket == "local":
        score += 16.0
        reasons.append("san_antonio_local")
    elif bucket == "nearby":
        score += 10.0
        reasons.append("nearby")
    elif bucket == "regional":
        preferred = int(policy.get("preferred_radius_miles", 50))
        score -= min(18.0, max(0.0, (int(distance) - preferred) * 0.10))
        risks.append("regional_drive_required")
    else:
        score -= 8.0
        risks.append("distance_unknown")

    if row.get("certified"):
        score += 4.0
        reasons.append("certified")

    if row.get("dealer_addon_warning"):
        score -= 12.0
        risks.append("dealer_mandatory_addon_risk")

    median = _comp_median(row, universe)
    market_delta_pct = None
    if median and median > 0:
        market_delta_pct = (price - median) / median * 100.0
        score += max(-12.0, min(14.0, -market_delta_pct * 1.1))
        if market_delta_pct <= -5:
            reasons.append("priced_below_local_comps")
        elif market_delta_pct >= 7:
            risks.append("priced_above_local_comps")

    if not row.get("vin"):
        score -= 4.0
        risks.append("vin_missing")
    if not row.get("source_url"):
        score -= 5.0
        risks.append("direct_listing_link_missing")

    otd_policy = dict(policy)
    if row.get("dealer_doc_fee") is not None:
        otd_policy["assumed_doc_fee"] = row["dealer_doc_fee"]

    out = dict(row)
    out.update({
        "deal_score": round(score, 1),
        "locality": bucket,
        "estimated_otd": estimate_otd(price, otd_policy),
        "comp_median_price": round(median, 2) if median else None,
        "market_delta_pct": round(market_delta_pct, 1) if market_delta_pct is not None else None,
        "reasons": reasons,
        "risks": risks,
    })
    return out


def rank_vehicles(rows: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    scope = [row for row in rows if eligible(row, policy)]
    scored = [score_vehicle(row, policy, scope) for row in scope]
    scored.sort(key=lambda row: (-float(row["deal_score"]), float(row["price"]), int(row["mileage"])))
    for idx, row in enumerate(scored, 1):
        row["rank"] = idx
    return scored
