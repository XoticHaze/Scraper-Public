"""Compact, public-only observation capture. No inferred closing outcomes."""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = ("auction_id", "auction_number", "lot_id", "lot_number", "inventory_id",
          "auction_location", "condition", "upc", "asin", "model", "model_number",
          "brand", "product_name", "current_bid", "total_bids", "unique_bidders",
          "expected_closing_utc", "estimated_post_tax_total")

def build_snapshot(report, catalog):
    scan = report.get("scan") or {}
    epoch = scan.get("inventory_source_epoch_utc")
    fresh = bool(epoch and scan.get("complete") and not scan.get("degraded_inventory_source")
                 and epoch == scan.get("scan_epoch_utc")
                 and epoch == catalog.get("inventory_source_epoch_utc")
                 and not catalog.get("degraded_inventory_source"))
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
            row.update({"identity": identity, "hunt_ids": hunts, "status": "observed_open"})
            rows.append(row)
    return {"schema": "macbid-public-observation-v1", "source_epoch_utc": epoch,
            "scan_epoch_utc": scan.get("scan_epoch_utc"),
            "coverage_complete": fresh, "filter_by": scan.get("filter_by"),
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
