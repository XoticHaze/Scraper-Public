"""Read-only source acceptance probe for auctioneer-owned Buy It Now inventory.

This intentionally does not collect HiBid auction lots, query private endpoints,
access bidder accounts, or treat the store inventory as current auction inventory.
No credentials, listing texts, products or personal data are printed or stored.
"""
from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ORIGIN = "https://paotexas.com"
ROUTES = (
    ("storefront_html", "/collections/all", "html"),
    ("storefront_products_json", "/collections/all/products.json?limit=5", "json"),
    ("catalog_products_json", "/products.json?limit=5", "json"),
)
USER_AGENT = "Scraper-Public-source-readiness/1.0 (read-only validation; contact auctioneer for feeds)"


def probe(name: str, path: str, fmt: str) -> tuple[str, str]:
    req = Request(
        ORIGIN + path,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json" if fmt == "json" else "text/html"},
    )
    try:
        with urlopen(req, timeout=15) as response:
            if not 200 <= response.status < 300:
                return name, f"HTTP_{response.status}"
            content_type = response.headers.get("Content-Type", "")
            body = response.read(500_000)
            if fmt == "html":
                lower = body.lower()
                useful = b"product" in lower and (b"auction" in lower or b"shop" in lower)
                return name, f"READABLE_HTML_{int(useful)}"
            if "json" not in content_type.lower() and not body.startswith(b"{"):
                return name, "NOT_JSON"
            payload = json.loads(body.decode("utf-8"))
            items = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                return name, "UNRECOGNIZED_SCHEMA"
            valid = sum(
                isinstance(item, dict) and bool(item.get("id")) and bool(item.get("title"))
                for item in items
            )
            return name, f"JSON_PRODUCTS_{len(items)}_VALID_{valid}"
    except HTTPError as exc:
        return name, f"HTTP_{exc.code}"
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        return name, f"ERROR_{type(exc).__name__}"


def main() -> int:
    results = dict(probe(*route) for route in ROUTES)
    print("SOURCE=paotexas_own_shop")
    print("SOURCE_TYPE=BUY_IT_NOW_STOREFRONT_NOT_HIBID_AUCTION")
    print("AUTHORITY=READ_ONLY_SOURCE_PROBE_NO_COLLECTOR")
    for name, value in sorted(results.items()):
        print(f"{name.upper()}={value}")
    feed_ok = any(
        value.startswith("JSON_PRODUCTS_") and not value.startswith("JSON_PRODUCTS_0_")
        for key, value in results.items()
        if key.endswith("_json")
    )
    html_ok = results.get("storefront_html") == "READABLE_HTML_1"
    print(f"STORE_SOURCE_READINESS={'PASS' if feed_ok and html_ok else 'FAIL'}")
    print("HIBID_AUCTION_INVENTORY_READINESS=NOT_PROVEN")
    return 0 if feed_ok and html_ok else 2


if __name__ == "__main__":
    sys.exit(main())
