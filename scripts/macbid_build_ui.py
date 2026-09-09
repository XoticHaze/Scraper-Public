from __future__ import annotations

import json
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from deal_engine.grouping import product_identity

REPORT = Path("results/macbid-deal-engine.json")
UI_SOURCE = Path("ui")
SITE = Path("site")

LOT_FIELDS = (
    "lot_id",
    "id",
    "auction_number",
    "auction_title",
    "lot_number",
    "auction_location",
    "condition",
    "current_bid",
    "retail_price",
    "estimated_pre_tax_total",
    "stated_retail_discount_pct",
    "stated_retail_savings",
    "deal_score",
    "provisional_max_bid",
    "expected_close_date",
    "expected_closing_utc",
    "hours_until_close",
    "unique_bidders",
    "total_bids",
    "image_url",
    "stock_image_url",
    "macbid_url",
)

OPTIONAL_VERIFICATION_FIELDS = (
    "market_price_status",
    "verified_new_price",
    "realistic_open_box_value",
    "verified_discount_pct",
    "verified_savings",
    "verdict",
    "verified_max_bid",
    "max_bid",
)


def compact_lot(lot: dict[str, Any]) -> dict[str, Any]:
    out = {key: lot.get(key) for key in LOT_FIELDS if lot.get(key) is not None}
    for key in OPTIONAL_VERIFICATION_FIELDS:
        if lot.get(key) is not None:
            out[key] = lot.get(key)
    return out


def product_metadata(lots: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(lots, key=lambda row: float(row.get("deal_score") or -10_000))
    metadata = {
        "identity": product_identity(best),
        "name": best.get("product_name") or best.get("title") or best.get("name") or "Unnamed item",
        "brand": best.get("brand") or best.get("manufacturer"),
        "category": best.get("category") or "Uncategorized",
        "upc": best.get("upc"),
        "model": best.get("model_number") or best.get("model"),
        "image_url": best.get("image_url") or best.get("stock_image_url"),
        "retail_price": best.get("retail_price") or best.get("retail"),
        "lot_count": len(lots),
    }
    for key in OPTIONAL_VERIFICATION_FIELDS:
        value = next((row.get(key) for row in lots if row.get(key) is not None), None)
        if value is not None:
            metadata[key] = value
    return metadata


def main() -> int:
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    scan = data.get("scan", {})
    policy = data.get("policy", {})
    final_epoch = int(scan.get("final_view_epoch_utc") or time.time())
    inventory = [
        lot
        for lot in data.get("inventory", [])
        if float(lot.get("expected_closing_utc") or 0) > final_epoch
    ]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lot in inventory:
        grouped[product_identity(lot)].append(lot)

    products: list[dict[str, Any]] = []
    for lots in grouped.values():
        lots.sort(key=lambda row: float(row.get("expected_closing_utc") or float("inf")))
        product = product_metadata(lots)
        product["lots"] = [compact_lot(row) for row in lots]
        products.append(product)

    products.sort(
        key=lambda product: min(
            float(lot.get("expected_closing_utc") or float("inf")) for lot in product["lots"]
        )
    )

    catalog = {
        "schema": "macbid-hunt-ui-v1",
        "generated_epoch_utc": int(time.time()),
        "source_scan_epoch_utc": scan.get("scan_epoch_utc"),
        "locations": policy.get("locations", []),
        "buyer_premium_rate": policy.get("buyer_premium_rate", 0.15),
        "lot_fee": policy.get("lot_fee", 3.0),
        "minimum_stated_retail": policy.get("minimum_stated_retail"),
        "product_count": len(products),
        "lot_count": len(inventory),
        "products": products,
    }

    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(UI_SOURCE, SITE)
    compact_json = json.dumps(catalog, separators=(",", ":"), ensure_ascii=False)
    (SITE / "catalog.json").write_text(compact_json, encoding="utf-8")
    (SITE / "catalog.js").write_text(
        "window.MACBID_CATALOG=" + compact_json + ";\n",
        encoding="utf-8",
    )
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    print(f"UI_PRODUCTS={len(products)}")
    print(f"UI_LOTS={len(inventory)}")
    print(f"UI_OUTPUT={SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
