from __future__ import annotations

import re
from typing import Any


def _text(product: dict[str, Any], lot: dict[str, Any] | None = None) -> str:
    lot = lot or {}
    values = [
        product.get("name"),
        product.get("brand"),
        product.get("category"),
        product.get("upc"),
        product.get("model"),
        lot.get("product_name"),
        lot.get("title"),
        lot.get("name"),
        lot.get("brand"),
        lot.get("manufacturer"),
        lot.get("category"),
        lot.get("model"),
        lot.get("model_number"),
        lot.get("description"),
    ]
    return re.sub(r"\s+", " ", " ".join(str(v) for v in values if v)).strip().lower()


def _contains(text: str, term: str) -> bool:
    return str(term).strip().lower() in text


def _any(text: str, terms: list[str] | None) -> list[str]:
    return [term for term in (terms or []) if _contains(text, term)]


def match_profile(
    profile: dict[str, Any],
    product: dict[str, Any],
    lot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    lot = lot or {}
    text = _text(product, lot)
    kind = profile.get("kind", "semantic")

    if kind == "semantic":
        excluded = _any(text, profile.get("exclude_any"))
        if excluded:
            return None
        required_all = profile.get("required_all") or []
        missing_all = [term for term in required_all if not _contains(text, term)]
        if missing_all:
            return None
        required_any = profile.get("required_any") or []
        required_hits = _any(text, required_any)
        if required_any and not required_hits:
            return None
        boost_hits = _any(text, profile.get("boost_any"))
        score = len(required_hits) * 2 + len(required_all) * 2 + len(boost_hits)
        if score < int(profile.get("minimum_signal_score") or 1):
            return None
        return {
            "score": score,
            "signals": (required_hits + required_all + boost_hits)[:12],
            "verification": profile.get("verification") or [],
            "compatibility_gate": profile.get("compatibility_gate"),
        }

    if kind == "ranked":
        excluded = _any(text, profile.get("exclude_signals"))
        if excluded:
            return None
        category_signals = profile.get("category_signals") or []
        category_hits = _any(text, category_signals)
        if category_signals and not category_hits:
            return None
        retail = float(lot.get("retail_price") or product.get("retail_price") or 0)
        bidders = int(lot.get("unique_bidders") or 0)
        deal_score = float(lot.get("deal_score") or 0)
        condition = lot.get("condition")
        preferred = profile.get("preferred_conditions") or []
        if retail < float(profile.get("minimum_stated_retail") or 0):
            return None
        if bidders > int(profile.get("maximum_bidders") or 10**9):
            return None
        if deal_score < float(profile.get("minimum_deal_score") or -10**9):
            return None
        if preferred and condition not in preferred:
            return None
        score = deal_score + min(retail / 50.0, 20) - bidders * 2
        return {
            "score": round(score, 2),
            "signals": category_hits[:8],
            "verification": profile.get("verification") or [],
            "compatibility_gate": profile.get("compatibility_gate"),
        }

    raise ValueError(f"unknown hunt profile kind: {kind}")


def match_profiles(
    profiles: list[dict[str, Any]],
    product: dict[str, Any],
    lot: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        match = match_profile(profile, product, lot)
        if match:
            matches[str(profile["id"])] = match
    return matches
