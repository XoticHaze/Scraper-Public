from __future__ import annotations

import re
from typing import Any

STATUS_RANK = {
    "verified": 60,
    "verified_with_requirements": 50,
    "variant_required": 40,
    "candidate": 30,
    "unknown": 20,
    "ruled_out": 0,
}


def _text(product: dict[str, Any], lot: dict[str, Any] | None = None) -> str:
    lot = lot or {}
    values = [
        product.get("name"), product.get("brand"), product.get("category"),
        product.get("model"), product.get("upc"), lot.get("product_name"),
        lot.get("title"), lot.get("name"), lot.get("brand"),
        lot.get("manufacturer"), lot.get("category"), lot.get("model"),
        lot.get("model_number"), lot.get("description"),
    ]
    return re.sub(r"\s+", " ", " ".join(str(v) for v in values if v)).strip().lower()


def _contains(text: str, term: str) -> bool:
    value = str(term or "").strip().lower()
    if not value:
        return False
    if re.fullmatch(r"[a-z0-9]+(?:[ -][a-z0-9]+)*", value):
        parts = re.split(r"[ -]+", value)
        pattern = r"(?<![a-z0-9])" + r"[\s-]+".join(re.escape(part) for part in parts) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return value in text


def _all(text: str, terms: list[str] | None) -> bool:
    return all(_contains(text, term) for term in (terms or []))


def _any(text: str, terms: list[str] | None) -> bool:
    return any(_contains(text, term) for term in (terms or []))


def _public_rule(rule: dict[str, Any], *, basis: str) -> dict[str, Any]:
    return {
        "target": rule.get("target") or "haos",
        "status": rule.get("status") or "unknown",
        "integration": rule.get("integration"),
        "local_control": rule.get("local_control"),
        "requirements": list(rule.get("requirements") or []),
        "note": rule.get("note"),
        "source": rule.get("source"),
        "sources": list(rule.get("sources") or []),
        "model": rule.get("model"),
        "transports": list(rule.get("transports") or []),
        "basis": basis,
        "rule_id": rule.get("id"),
    }


def evaluate_compatibility(
    matrix: dict[str, Any],
    product: dict[str, Any],
    lot: dict[str, Any] | None = None,
    *,
    target: str = "haos",
) -> dict[str, Any]:
    identity = str(product.get("identity") or "")
    overrides = [
        row for row in (matrix.get("exact_overrides") or [])
        if row.get("target", "haos") == target and str(row.get("identity") or "") == identity
    ]
    if overrides:
        return _public_rule(overrides[0], basis="exact_identity")

    text = _text(product, lot)
    matches: list[dict[str, Any]] = []

    for rule in matrix.get("capability_rules") or []:
        if rule.get("target", "haos") != target:
            continue
        all_terms = list(rule.get("match_all") or [])
        any_terms = list(rule.get("match_any") or [])
        if all_terms and not _all(text, all_terms):
            continue
        if any_terms and not _any(text, any_terms):
            continue
        if not all_terms and not any_terms:
            continue
        matches.append(_public_rule(rule, basis="capability"))

    for rule in matrix.get("vendor_rules") or []:
        if rule.get("target", "haos") != target:
            continue
        if not _any(text, list(rule.get("match_any") or [])):
            continue
        product_terms = list(rule.get("product_any") or [])
        if product_terms and not _any(text, product_terms):
            continue
        matches.append(_public_rule(rule, basis="vendor_integration"))

    if not matches:
        return {
            "target": target,
            "status": "unknown",
            "integration": None,
            "local_control": None,
            "requirements": ["exact protocol/integration must be identified"],
            "note": "No compatibility proof has been established from the current identity or product signals.",
            "basis": "none",
        }

    matches.sort(key=lambda row: STATUS_RANK.get(str(row.get("status")), 0), reverse=True)
    chosen = dict(matches[0])
    chosen["detected_paths"] = [
        {
            "status": row.get("status"),
            "integration": row.get("integration"),
            "basis": row.get("basis"),
            "rule_id": row.get("rule_id"),
        }
        for row in matches[:8]
    ]
    return chosen


def compatibility_allows_hunt(compatibility: dict[str, Any], gate: str | None) -> bool:
    if not gate:
        return True
    if gate == "haos":
        return str(compatibility.get("status") or "unknown") != "ruled_out"
    return True
