"""Compact, public-only observation capture. No inferred closing outcomes."""
from __future__ import annotations

import json
import hashlib
import re
from urllib.parse import urlsplit
from pathlib import Path

FIELDS = ("auction_id", "auction_number", "lot_id", "lot_number", "inventory_id",
          "auction_location", "condition", "upc", "asin", "model", "model_number",
          "brand", "product_name", "current_bid", "total_bids", "unique_bidders",
          "expected_closing_utc", "estimated_post_tax_total", "retail_price", "legacy_msrp_score",
          "market_price_status", "market_value_authoritative", "verified_discount_pct",
          "market_reference_value", "verified_max_bid")

def build_snapshot(report, catalog):
    scan = report.get("scan") or {}
    epoch = scan.get("inventory_source_epoch_utc")
    fresh = bool(epoch and scan.get("complete") and not scan.get("degraded_inventory_source")
                 and epoch == scan.get("scan_epoch_utc")
                 and epoch == catalog.get("inventory_source_epoch_utc")
                 and not catalog.get("degraded_inventory_source"))
    scope = {"filter": re.sub(r"expected_closing_utc:>\d+", "expected_closing_utc:>SCAN_EPOCH", str(scan.get("filter_by") or "")),
             "locations": sorted(catalog.get("locations") or [])}
    scope_id = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    rows = []
    seen = set()
    by_lot = {}
    for product in catalog.get("products", []):
        for lot in product.get("lots", []):
            by_lot[(str(lot.get("auction_number")), str(lot.get("lot_id")))] = (
                product.get("identity"), sorted(product.get("hunt_ids") or []))
    if fresh:
        for lot in report.get("inventory", []):
            key = (str(lot.get("auction_id") or ""), str(lot.get("lot_id") or ""))
            if not all(key) or key in seen:
                continue
            seen.add(key)
            identity, hunts = by_lot.get((str(lot.get("auction_number")), key[1]), (None, []))
            row = {k: lot[k] for k in FIELDS if k in lot and isinstance(lot[k], (str, int, float))}
            source = urlsplit(str(lot.get("macbid_url") or ""))
            if source.scheme == "https" and source.netloc == "www.mac.bid" and source.path == f"/auction/{lot.get('auction_number')}/lot/{lot.get('lot_number')}" and not source.query and not source.fragment:
                row["macbid_url"] = source.geturl()
            row.update({"identity": identity, "hunt_ids": hunts, "status": "observed_open", "source_epoch_utc": epoch})
            rows.append(row)
    return {"schema": "macbid-public-observation-v1", "source_epoch_utc": epoch,
            "scan_epoch_utc": scan.get("scan_epoch_utc"),
            "coverage_complete": fresh, "filter_by": scan.get("filter_by"), "scope": scope, "scope_id": scope_id,
            "fee_scenario": {k: catalog.get(k) for k in ("buyer_premium_rate", "lot_fee", "sales_tax_rate")},
            "observations": rows, "observed_lots": len(rows)}

def main():
    report = json.loads(Path("results/macbid-deal-engine.json").read_text())
    catalog = json.loads(Path("site/catalog.json").read_text())
    snapshot = build_snapshot(report, catalog)
    Path("results/macbid-public-observations.json").write_text(json.dumps(snapshot, separators=(",", ":")))
    print("PUBLIC_OBSERVATIONS", snapshot["observed_lots"], "COMPLETE", snapshot["coverage_complete"])

if __name__ == "__main__":
    main()
