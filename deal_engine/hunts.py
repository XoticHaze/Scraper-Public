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
    """Match semantic terms without accidental substring collisions.

    Simple word/phrase terms use token boundaries and accept a trailing plural on
    the final alphabetic word. Punctuated model-ish terms keep literal matching.
    This prevents examples such as `tv` -> `utv`, `phone` -> `microphone`, and
    `tablet` -> `tabletop` while still allowing `monitor` -> `monitors`.
    """

    value = str(term).strip().lower()
    if not value:
        return False
    if re.fullmatch(r"[a-z0-9]+(?:[ -][a-z0-9]+)*", value):
        parts = re.split(r"[ -]+", value)
        regex_parts: list[str] = []
        for index, part in enumerate(parts):
            piece = re.escape(part)
            if index == len(parts) - 1 and part.isalpha() and len(part) > 2 and not part.endswith("s"):
                piece += "s?"
            regex_parts.append(piece)
        pattern = r"(?<![a-z0-9])" + r"[\s-]+".join(regex_parts) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return value in text


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
        must_match_any = profile.get("must_match_any") or []
        must_hits = _any(text, must_match_any)
        if must_match_any and not must_hits:
            return None
        boost_hits = _any(text, profile.get("boost_any"))
        score = (
            len(required_hits) * 2
            + len(required_all) * 2
            + len(must_hits) * 2
            + len(boost_hits)
        )
        if score < int(profile.get("minimum_signal_score") or 1):
            return None
        return {
            "score": score,
            "signals": (required_hits + required_all + must_hits + boost_hits)[:12],
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
