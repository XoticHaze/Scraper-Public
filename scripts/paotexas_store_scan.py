"""Collect public fixed-price products from the auctioneer's own storefront.

This does NOT access HiBid or its auction lot catalog. Zero credentials, bids,
account state or session storage. A missing/invalid page fails closed rather
than being presented as a live inventory snapshot.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from deal_engine.storefront import build_catalog

SOURCE = "https://paotexas.com/collections/all/products.json"
DEFAULT_OUTPUT = Path("results/paotexas-store.json")
BATCH_SIZE = 50
MAX_PAGES = 8


def fetch_pages() -> tuple[list[dict], int]:
    all_items: list[dict] = []
    seen: set[str] = set()
    fetched_pages = 0
    for page in range(1, MAX_PAGES + 1):
        req = Request(
            f"{SOURCE}?limit={BATCH_SIZE}&page={page}",
            headers={
                "User-Agent": "Scraper-Public-storefront-research/1.0",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        with urlopen(req, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"storefront HTTP {response.status} page={page}")
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError(f"storefront response oversized page={page}")
        payload = json.loads(body)
        products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(products, list):
            raise RuntimeError(f"storefront unrecognized schema page={page}")
        fetched_pages += 1
        added = 0
        for item in products:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            identity = str(item["id"])
            if identity not in seen:
                seen.add(identity)
                all_items.append(item)
                added += 1
        if not products or len(products) < BATCH_SIZE or added == 0:
            break
    return all_items, fetched_pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    products, pages = fetch_pages()
    report = build_catalog(
        products,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    if not products or report["product_count"] < 1:
        raise RuntimeError("no valid available Buy It Now products; do not publish empty snapshot as live")
    report["source_pages"] = pages
    report["source_raw_product_count"] = len(products)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"PAOTEXAS_SOURCE=BUY_IT_NOW_NOT_HIBID_AUCTION pages={pages} raw={len(products)}")
    print(f"PAOTEXAS_PRODUCTS={report['product_count']} focused={report['focused_count']}")
    print("PAOTEXAS_SOURCE_AUTHORITY=FIRST_PARTY_FIXED_PRICE_ONLY")
    print(f"PAOTEXAS_OUTPUT={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
