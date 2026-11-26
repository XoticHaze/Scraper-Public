from __future__ import annotations

from datetime import date, datetime
from statistics import mean, median
from math import isfinite, floor, ceil
from typing import Any
from urllib.parse import urlparse
from deal_engine.market_enrichment import reject_price_outliers

SECONDARY_CONDITIONS = {"open_box", "used", "refurbished", "certified_refurbished"}


def market_freshness(
    observed_at: Any,
    *,
    as_of: Any = None,
    fresh_days: int = 7,
    stale_after_days: int = 30,
) -> dict[str, Any]:
    """Classify external pricing age so old observations cannot silently drive bids."""

    def _date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            raw = value.strip()
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                return None
        return None

    observed = _date(observed_at)
    current = _date(as_of) if as_of is not None else date.today()
    if observed is None or current is None:
        return {"age_days": None, "freshness": "unknown", "authoritative": False}

    if observed > current:
        return {"age_days": None, "freshness": "unknown", "authoritative": False}
    age_days = (current - observed).days
    if age_days <= int(fresh_days):
        freshness = "fresh"
    elif age_days <= int(stale_after_days):
        freshness = "aging"
    else:
        freshness = "stale"
    return {
        "age_days": age_days,
        "freshness": freshness,
        "authoritative": freshness in {"fresh", "aging"},
    }


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
        if condition in conditions and price is not None and isfinite(price) and price > 0:
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


def summarize_market_value(record: dict[str, Any], *, as_of=None, fresh_days=7, stale_after_days=30) -> dict[str, Any]:
    observations = list(record.get("observations") or [])
    current = [row for row in observations if as_of is None or market_freshness(
        row.get("observed_at"), as_of=as_of, fresh_days=fresh_days,
        stale_after_days=stale_after_days)["authoritative"]]
    current = [row for row in current if row.get("availability") not in {"out_of_stock", "sold", "unavailable"}
               and row.get("observation_kind") != "historical_sale"]
    current = [row for row in current if str(row.get("condition") or "").strip().lower() in (SECONDARY_CONDITIONS | {"new"}) and (p := _number(row.get("price"))) is not None and isfinite(p) and p > 0]
    # Compare outliers only within the same condition cohort and freshness window.
    current = [row for condition in sorted(SECONDARY_CONDITIONS | {'new'})
               for row in reject_price_outliers([r for r in current if str(r.get('condition') or '').strip().lower() == condition])]
    current_new = price_stats(current, {"new"})
    open_box_used = price_stats(current, SECONDARY_CONDITIONS)
    current_domains = {(urlparse(str(row.get("url") or "")).hostname or "").lower().removeprefix("www.") for row in current}
    current_domains.discard("")
    confidence = "high" if len(current_domains) >= 2 else "medium" if current_domains else "unknown"
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
        "price_confidence": confidence,
        "observed_at": max((str(row.get("observed_at") or "") for row in current), default=None) if as_of is not None else record.get("observed_at"),
        "current_source_count": len(current),
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
    as_of: Any = None,
    fresh_days: int = 7,
    stale_after_days: int = 30,
) -> dict[str, Any]:
    """Derive market-backed acquisition ceilings from public external observations.

    MAC.BID stated retail is intentionally not an input. Exact external identity and
    price observations become authoritative when this record is present.
    """
    summary = summarize_market_value(record, as_of=as_of or date.today().isoformat(), fresh_days=fresh_days, stale_after_days=stale_after_days)
    freshness = market_freshness(
        summary.get("observed_at") or record.get("observed_at"),
        as_of=as_of,
        fresh_days=fresh_days,
        stale_after_days=stale_after_days,
    )
    if not summary["current_source_count"]:
        freshness["authoritative"] = False
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

    max_all_in = (
        reference_value * allocation_ratio
        if reference_value is not None and freshness["authoritative"]
        else None
    )
    max_bid = reverse_max_bid(
        max_all_in,
        premium_rate=premium_rate,
        lot_fee=lot_fee,
        sales_tax_rate=sales_tax_rate,
    )

    all_in = _number(current_all_in)
    discount_pct = None
    savings = None
    if freshness["authoritative"] and reference_value and all_in is not None:
        discount_pct = (1.0 - all_in / reference_value) * 100.0
        savings = reference_value - all_in

    return {
        "market_price_status": "verified_external" if freshness["authoritative"] else "stale_external",
        "market_value_age_days": freshness["age_days"],
        "market_value_freshness": freshness["freshness"],
        "market_value_authoritative": freshness["authoritative"],
        "market_value_confidence": summary.get("price_confidence"),
        "market_identity_confidence": summary.get("identity_confidence"),
        "market_value_observed_at": summary.get("observed_at"),
        "market_value_source_count": summary.get("current_source_count"),
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


def compare_protected_offers(product: dict[str, Any], offers: list[dict[str, Any]], *,
                             as_of: str, sales_tax_rate: float, premium_rate: float,
                             lot_fee: float, as_of_epoch: int | None = None,
                             admitted_sources: dict[str, Any] | None = None,
                             delivery_scope: str = "San Antonio, TX") -> dict[str, Any]:
    """Exact delivered alternatives; general policy or cached price is not a checkout quote."""
    def norm(value):
        return str(value or "").strip().casefold()
    def cost(value):
        n = _number(value) if not isinstance(value, bool) else None
        return n if n is not None and isfinite(n) and n >= 0 else None
    def timestamp(value):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.timestamp() if dt.tzinfo is not None else None
        except (ValueError, TypeError, OverflowError):
            return None
    def safe_url(value):
        try:
            p=urlparse(str(value or ""))
            return p.scheme=="https" and bool(p.hostname) and not p.username and not p.password and not p.query and not p.fragment
        except ValueError:
            return False
    rows = []
    for offer in offers:
        identity, offer_id = norm(product.get("identity")), norm(offer.get("identity"))
        brand, model = norm(product.get("brand")), norm(product.get("model"))
        obrand, omodel = norm(offer.get("brand")), norm(offer.get("model"))
        exact_id = bool(identity and identity == offer_id)
        exact_model = bool(brand and model and brand == obrand and model == omodel)
        if not (exact_id or exact_model):
            continue
        if not safe_url(offer.get("url")):
            continue
        if (identity and offer_id and identity != offer_id) or (brand and obrand and brand != obrand) or (model and omodel and model != omodel):
            continue
        price, shipping, fees, tax = (cost(offer.get(k)) for k in ("price", "shipping", "mandatory_fees", "checkout_tax"))
        estimated = round((price + shipping + fees) * (1 + sales_tax_rate), 2) if None not in (price, shipping, fees) else None
        delivered = round(price + shipping + fees + tax, 2) if None not in (price, shipping, fees, tax) else None
        observed = timestamp(offer.get("observed_at"))
        policy = (admitted_sources or {}).get(offer.get("source_id"), {})
        limit = cost(policy.get("max_age_hours"))
        expires = timestamp(policy.get("expires_at"))
        permitted = (policy.get("public_projection_allowed") is True
                     and policy.get("collection_authorized") is True
                     and policy.get("durable_retention_allowed") is True
                     and expires is not None and as_of_epoch is not None
                     and as_of_epoch < expires and limit is not None and 0 < limit <= 24
                     and bool(policy.get("authorization_ref")))
        fresh = bool(permitted and observed is not None and 0 <= as_of_epoch-observed <= limit*3600)
        return_days = cost(offer.get("return_days"))
        eligible = bool(delivered is not None and price > 0 and offer.get("live_verified") is True
                        and offer.get("availability") == "in_stock" and offer.get("seller_verified") is True
                        and offer.get("fixed_price") is True and offer.get("item_return_eligible") is True
                        and offer.get("delivery_scope") == delivery_scope and offer.get("checkout_verified") is True
                        and return_days and fresh
                        and offer.get("condition") in {"new", "open_box", "used", "refurbished", "certified_refurbished"}
                        and offer.get("currency") == "USD"
                        and safe_url(offer.get("url")) and safe_url(offer.get("policy_url")))
        rows.append({**{k: offer.get(k) for k in ("source_label", "url", "condition", "price",
                    "shipping", "mandatory_fees", "return_days", "warranty_days", "availability", "observed_at",
                    "evidence_note")}, "estimated_delivered_total": estimated,
                    "verified_delivered_total": delivered if eligible else None,
                    "policy_url": offer.get("policy_url") if safe_url(offer.get("policy_url")) else None,
                    "eligibility_status": "verified" if eligible else "context_only",
                    "eligible": eligible})
    eligible_rows = [r for r in rows if r["eligible"]]
    best = min(eligible_rows, key=lambda r: r["verified_delivered_total"]) if eligible_rows else None
    # Strictly greater than 50% off, in whole cents.
    ceiling = max(0, ceil(best["verified_delivered_total"] * 50 - 1e-8) - 1) / 100 if best else None
    hammer = floor(max(0, (ceiling / (1 + sales_tax_rate) - lot_fee) / (1 + premium_rate)) * 100) / 100 if ceiling is not None else None
    return {"offers": rows, "best_protected_offer": best, "max_auction_all_in": ceiling,
            "max_auction_hammer": hammer, "tax_basis": "verified checkout tax for comparator; estimated local auction tax"}

def rebuild_market_views(report: dict[str, Any], *, active_inventory: list[dict[str, Any]]) -> None:
    """Final report and UI must share the same enriched lots, not separate MSRP rankings."""
    from deal_engine.grouping import collapse_ranked
    limits = (report.get("policy") or {}).get("views") or {}
    def close(row):
        return _number(row.get("expected_closing_utc")) or float("inf")
    def competition(row):
        return int(row.get("unique_bidders") or 0), int(row.get("total_bids") or 0)
    def verified(row):
        return (row.get("market_price_status") == "verified_external"
                and row.get("market_value_authoritative") is True
                and _number(row.get("verified_discount_pct")) is not None)
    def discovery(row):
        return -float(row.get("deal_score") or 0), close(row), competition(row)
    priced = [row for row in active_inventory if verified(row)]
    unknown = [row for row in active_inventory if not verified(row)]
    ranked = sorted(priced, key=lambda r: (-float(r["verified_discount_pct"]), competition(r), close(r)))
    views = {
        "ending_soon": sorted(active_inventory, key=lambda r: (close(r), competition(r))),
        "best_value": ranked,
        "low_competition": sorted(active_inventory, key=lambda r: (competition(r), close(r))),
        "verification_queue": sorted(unknown, key=discovery),
        "discovery_candidates": sorted(unknown, key=discovery),
    }
    report["views"] = {key: collapse_ranked(rows)[:int(limits.get(key, 100))] for key, rows in views.items()}
    report["market_publication"] = {"schema": "macbid-market-joined-report-v1",
        "verified_lots": len(priced), "discovery_lots": len(unknown),
        "best_value_basis": "current exact external valuation only",
        "discovery_basis": "condition, competition and closing time only"}
