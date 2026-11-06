"""Manual, read-only single-item probes. No schedules, auctions bids, or search discovery."""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from deal_engine.marketplace import (
    normalize_bestbuy_open_box, normalize_bestbuy_products, normalize_ebay_item,
)


class SourceAccessError(RuntimeError):
    pass


def _get_json(url, *, headers=None, timeout=12):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Scraper-Public/marketplace-onboarding", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as resp:
            body = resp.read(2_000_001)
            if len(body) > 2_000_000:
                raise SourceAccessError("API response exceeds size bound")
            return json.loads(body)
    except HTTPError as exc:
        # Never print URL: Best Buy keys are query parameters.
        raise SourceAccessError(f"provider HTTP {exc.code}") from None
    except (URLError, ValueError, json.JSONDecodeError):
        raise SourceAccessError("provider request failed or invalid JSON") from None


def get_ebay_item(item_id, *, token=None):
    """Use an already admitted application token; do not attempt customer auth."""
    item_id = str(item_id)
    if not re.fullmatch(r"(?:v1\|\d{8,20}\|\d+|\d{8,20})", item_id):
        raise ValueError("invalid item identifier")
    token = token or os.environ.get("EBAY_APP_TOKEN")
    if not token:
        raise SourceAccessError("EBAY_APP_TOKEN not configured")
    if item_id.isdigit():
        url = "https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=" + item_id
    else:
        url = "https://api.ebay.com/buy/browse/v1/item/" + quote(item_id, safe="")
    return _get_json(url, headers={"Authorization": "Bearer " + token, "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})


def get_bestbuy_sku(sku, *, key=None, open_box=False):
    sku = str(sku)
    if not re.fullmatch(r"\d{5,15}", sku):
        raise ValueError("invalid SKU")
    key = key or os.environ.get("BESTBUY_API_KEY")
    if not key:
        raise SourceAccessError("BESTBUY_API_KEY not configured")
    if open_box:
        path = f"/beta/products/{sku}/openBox"
    else:
        path = f"/v1/products/{sku}.json"
    return _get_json("https://api.bestbuy.com" + path + "?apiKey=" + quote(key, safe=""))


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Read-only single-item API probe; never submits a bid or purchase")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--ebay-item-id")
    group.add_argument("--bestbuy-sku")
    p.add_argument("--bestbuy-open-box", action="store_true")
    args = p.parse_args(argv)
    if args.bestbuy_open_box and not args.bestbuy_sku:
        p.error("--bestbuy-open-box requires --bestbuy-sku")
    try:
        if args.ebay_item_id:
            output = [normalize_ebay_item(get_ebay_item(args.ebay_item_id))]
        else:
            response = get_bestbuy_sku(args.bestbuy_sku, open_box=args.bestbuy_open_box)
            output = (normalize_bestbuy_open_box(response) if args.bestbuy_open_box
                      else normalize_bestbuy_products(response))
        print(json.dumps({"schema": "marketplace-manual-probe-v1", "source_live_request": True,
                          "offer_count": len(output), "offers": output}, indent=2))
        return 0
    except (SourceAccessError, ValueError, TypeError) as exc:
        print(f"PROBE_NOT_AVAILABLE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
