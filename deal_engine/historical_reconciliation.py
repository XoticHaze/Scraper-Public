"""Strict reconciliation of already-observed public lots against explicit closure evidence."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TIME_RE = r"(\d{1,2}/\d{1,2}/\d{4})\s+at\s+(\d{1,2}:\d{2}\s+[AP]M)"
LOCATION_ZONES = {"San Antonio": "America/Chicago"}
MONEY = r"([\d,]+(?:\.\d{1,2})?)"

def lot_key(row):
    return (str(row.get("auction_id") or ""), str(row.get("lot_number") or "").upper())

def canonical_lot_url(row):
    auction, lot = str(row.get("auction_number") or ""), str(row.get("lot_number") or "")
    if not re.fullmatch(r"[A-Z0-9-]{6,40}", auction) or not re.fullmatch(r"[A-Z0-9-]{1,24}", lot):
        return None
    return f"https://www.mac.bid/auction/{auction}/lot/{lot}"

def parse_closed_listing(row, *, href, text):
    """Only exact links and explicit Won for/Not Sold. Missing is unresolved."""
    expected = canonical_lot_url(row)
    if not expected or href != expected:
        return None
    lot = re.escape(str(row["lot_number"]))
    match = re.search(r"\bLot\s*#\s*" + lot + r"\s+(?:Won\s+for\s+\$" + MONEY +
                      r"|(Not\s+Sold))\s+Closed\s+on\s+" + TIME_RE, text, re.I)
    if not match:
        return None
    hammer = float(match[1].replace(",", "")) if match[1] else None
    if hammer is not None and not 0 < hammer < 1_000_000:
        return None
    return {"status": "closed_sold_verified" if hammer is not None else "closed_unsold_verified",
            "final_hammer": hammer, "date": match[3], "time": match[4]}

def reconcile_detail(row, listing, *, href, detail_text, verified_epoch_utc, scope_id, diagnostic=None):
    """Require prior lot identity and detail evidence; use the conservative minute end."""
    def reject(reason):
        if diagnostic is not None:
            diagnostic["reason"] = reason
        return None
    if listing is None or href != canonical_lot_url(row):
        return reject("listing_or_url_missing")
    if not re.search(r"Lot Number:\s*" + re.escape(str(row.get("auction_number"))) +
                     r"\s*/\s*" + re.escape(str(row.get("lot_number"))) + r"\b", detail_text, re.I):
        return reject("lot_number_mismatch")
    # Preserve only the public numeric identifier, not raw page/account text.
    reported = re.search(r"Mac\.Bid ID:\s*([0-9][0-9,]{0,20})\b", detail_text, re.I)
    public_detail_id = reported.group(1).replace(",", "") if reported else None
    source_lot_id = str(row.get("lot_id") or "")
    source_inventory_id = str(row.get("inventory_id") or "")
    # The live public page exposes inventory_id, not lot_id (12/12 exact
    # cases, run 45826590781). Older fixtures may contain only the displayed ID.
    # When both source identifiers exist, require the inventory ID, never an
    # either/or fallback. All remaining independent identity and price checks stand.
    expected_detail_id = source_inventory_id or source_lot_id
    if not re.fullmatch(r"[0-9]{1,20}", expected_detail_id) or public_detail_id != expected_detail_id:
        if diagnostic is not None:
            diagnostic["public_detail_id"] = public_detail_id
            diagnostic["source_lot_id"] = str(row.get("lot_id") or "")
            diagnostic["source_inventory_id"] = str(row.get("inventory_id") or "")
            diagnostic["matches_inventory_id"] = bool(public_detail_id and public_detail_id == str(row.get("inventory_id")))
        return reject("lot_id_mismatch")
    token = str(row.get("upc") or row.get("asin") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{8,14}", token):
        return reject("identity_token_missing")
    if not re.search(r"UPC:\s*" + re.escape(token) + r"\b", detail_text, re.I):
        return reject("upc_mismatch")
    condition = str(row.get("condition") or "")
    if condition not in {"LIKE NEW", "OPEN BOX"} or not re.search(r"Condition:\s*" + re.escape(condition) + r"\b", detail_text, re.I):
        return reject("condition_mismatch")
    close = re.search(r"Auction Closed\s+" + TIME_RE, detail_text, re.I)
    if not close or close[1] != listing["date"] or close[2].upper() != listing["time"].upper():
        return reject("close_time_mismatch")
    if listing["status"] == "closed_sold_verified":
        # The price displayed on the lot page must agree with the explicit past-auction result.
        prices = re.findall(r"(?m)^\s*\$" + MONEY + r"\s*$", detail_text)
        if "winner saved" not in detail_text.lower() or not prices or float(prices[0].replace(",", "")) != listing["final_hammer"]:
            return reject("hammer_mismatch")
    elif not re.search(r"\bLot Not Sold\b", detail_text, re.I):
        return reject("unsold_marker_missing")
    zone = LOCATION_ZONES.get(row.get("auction_location"))
    if not zone:
        return reject("location_unknown")
    local = datetime.strptime(close[1] + " " + close[2].upper(), "%m/%d/%Y %I:%M %p").replace(tzinfo=ZoneInfo(zone))
    # Display is minute precision. Reject ambiguous DST folds rather than guess.
    if local.utcoffset() != local.replace(fold=1).utcoffset():
        return reject("ambiguous_close_time")
    close_start = int(local.timestamp())
    close_end = close_start + 59
    observed = row.get("source_epoch_utc")
    if not isinstance(observed, int) or not observed < close_start <= close_end < verified_epoch_utc:
        return reject("observation_time_conflict")
    key = lot_key(row)
    if not all(key) or not key[0].isdigit():
        return reject("invalid_lot_key")
    return {"auction_id": key[0], "auction_number": row["auction_number"], "lot_number": key[1],
            "lot_id": row["lot_id"], "inventory_id": row.get("inventory_id"),
            "public_detail_id":public_detail_id,
            "public_detail_id_kind":"inventory_id" if source_inventory_id else "legacy_displayed_id",
            "identity": row.get("identity"), "condition": condition,
            "auction_location": row["auction_location"], "hunt_ids": row.get("hunt_ids") or [],
            "source_url": f"https://www.mac.bid/past-auctions/{key[0]}",
            "lot_source_url": href, "status": listing["status"], "final_hammer": listing["final_hammer"],
            "closed_epoch_utc": close_end, "close_minute_start_utc": close_start, "close_time_precision": "minute",
            "verified_epoch_utc": verified_epoch_utc, "prediction_epoch_utc": observed,
            "reconciliation_level": "lot_detail_reconciled", "scope_id": scope_id,
            "training_eligible": bool(row.get("identity") and scope_id and scope_id != "recovered-legacy-retail-floor-40" and source_inventory_id),
            "observed_hammer": row.get("current_bid"), "legacy_msrp": row.get("retail_price"),
            "legacy_msrp_score": row.get("legacy_msrp_score")}

def detail_only_evidence(row, *, href, detail_text, verified_epoch_utc, scope_id):
    """An exact public detail can document a close, but cannot replace listing corroboration.

    Keep this evidence on the pending row. It is not a training outcome and
    must not silently be counted as an independently reconciled sale.
    """
    close = re.search(r"Auction Closed\s+" + TIME_RE, detail_text, re.I)
    if not close:
        return None
    unsold = bool(re.search(r"\bLot Not Sold\b", detail_text, re.I))
    sold = bool(re.search(r"\bWinner saved\b", detail_text, re.I))
    if unsold == sold:
        return None
    hammer = None
    if sold:
        # Require the explicit displayed winner price adjacent to the retail
        # comparison and winner label, not an arbitrary dollar amount.
        block = re.search(r"(?m)^\s*\$" + MONEY + r"\s*\n\s*\$" + MONEY +
                          r"\s*\n\s*Winner saved\b", detail_text, re.I)
        if not block:
            return None
        hammer = float(block[1].replace(",", ""))
        if not 0 < hammer < 1_000_000:
            return None
    listing = {"status": "closed_unsold_verified" if unsold else "closed_sold_verified",
               "final_hammer": hammer, "date": close[1], "time": close[2]}
    result = reconcile_detail(row, listing, href=href, detail_text=detail_text,
                              verified_epoch_utc=verified_epoch_utc, scope_id=scope_id)
    if not result:
        return None
    return {"source_url": href, "status": "detail_only_unsold" if unsold else "detail_only_sold",
            "reported_hammer": hammer, "closed_epoch_utc": result["closed_epoch_utc"],
            "verified_epoch_utc": verified_epoch_utc, "reconciliation_level": "lot_detail_only",
            "training_eligible": False}


def pending_closed_candidates(previous, current):
    """Missing from a complete matching scan is only a candidate for reconciliation."""
    if not (previous.get("coverage_complete") and current.get("coverage_complete")
            and previous.get("scope_id") and previous["scope_id"] == current.get("scope_id")
            and isinstance(previous.get("source_epoch_utc"), int)
            and isinstance(current.get("source_epoch_utc"), int)
            and previous["source_epoch_utc"] < current["source_epoch_utc"]):
        return []
    active = {lot_key(row) for row in current.get("observations", [])}
    pending = []
    for row in previous.get("observations", []):
        close = row.get("expected_closing_utc")
        if all(lot_key(row)) and lot_key(row) not in active and isinstance(close, (int, float)) and close <= current["source_epoch_utc"]:
            pending.append(dict(row, status="missing_unresolved", scope_id=previous["scope_id"]))
    return pending
