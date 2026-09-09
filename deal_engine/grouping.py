from __future__ import annotations

import re
from typing import Any

NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: Any) -> str:
    return NON_ALNUM.sub(" ", str(text or "").lower()).strip()


def product_identity(lot: dict[str, Any]) -> str:
    """Best-effort stable product identity for deduplicating repeated lots."""
    upc = str(lot.get("upc") or "").strip().upper()
    if upc and not upc.startswith("NA"):
        return f"upc:{upc}"

    asin = str(lot.get("asin") or "").strip().upper()
    if asin:
        return f"asin:{asin}"

    model = normalize(lot.get("model_number") or lot.get("model"))
    brand = normalize(lot.get("brand") or lot.get("manufacturer"))
    if model:
        return f"model:{brand}:{model}"

    name = normalize(lot.get("product_name") or lot.get("title") or lot.get("name"))
    retail = lot.get("retail_price") if lot.get("retail_price") is not None else lot.get("retail")
    return f"name:{name}:retail:{retail}"


def alternate_summary(lot: dict[str, Any]) -> dict[str, Any]:
    return {
        "lot_id": lot.get("lot_id") or lot.get("id"),
        "auction_number": lot.get("auction_number"),
        "lot_number": lot.get("lot_number"),
        "auction_location": lot.get("auction_location"),
        "condition": lot.get("condition"),
        "current_bid": lot.get("current_bid"),
        "estimated_pre_tax_total": lot.get("estimated_pre_tax_total"),
        "expected_close_date": lot.get("expected_close_date"),
        "unique_bidders": lot.get("unique_bidders"),
        "total_bids": lot.get("total_bids"),
        "macbid_url": lot.get("macbid_url"),
    }


def collapse_ranked(rows: list[dict[str, Any]], max_alternates: int = 8) -> list[dict[str, Any]]:
    """Collapse an already-ranked lot list, preserving the best lot per product."""
    output: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}

    for lot in rows:
        key = product_identity(lot)
        primary = by_key.get(key)
        if primary is None:
            primary = dict(lot)
            primary["product_identity"] = key
            primary["duplicate_lot_count"] = 1
            primary["alternative_lots"] = []
            by_key[key] = primary
            output.append(primary)
            continue

        primary["duplicate_lot_count"] += 1
        if len(primary["alternative_lots"]) < max_alternates:
            primary["alternative_lots"].append(alternate_summary(lot))

    return output
