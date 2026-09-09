from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Request, sync_playwright

LOCATION_PAGE = "https://www.mac.bid/locations/san-antonio"
OUTPUT = Path("results/macbid-direct-hunt.json")
TERMS = (
    "Kwikset",
    "Schlage",
    "Aqara",
    "Yale",
    "smart lock",
    "Z-Wave",
    "Zigbee",
    "Matter",
    "Thread",
    "Chamberlain",
    "LiftMaster",
)

SAFE_DOC_KEYS = {
    "id", "lot_id", "lot_number", "auction_id", "auction_number", "title", "name",
    "description", "condition", "condition_name", "retail_price", "retail", "current_bid",
    "current_price", "price", "end_time", "closing_date", "closing_date_utc", "pickup_date",
    "location_id", "location_name", "building_id", "building_name", "city_state", "code",
    "upc", "asin", "model", "model_number", "manufacturer", "brand", "stock_image_url",
    "image_url", "slug", "url", "is_open", "status", "total_bids", "unique_bidders",
    "watchers_count", "box_size", "category", "auction_slug"
}
SAFE_SEARCH_KEYS = {
    "collection", "q", "query_by", "filter_by", "sort_by", "facet_by", "page", "per_page",
    "max_facet_values", "include_fields", "exclude_fields", "highlight_fields", "num_typos",
    "prefix", "typo_tokens_threshold", "group_by", "group_limit"
}
SENSITIVE = re.compile(r"(?:token|auth|cookie|session|secret|api.?key|signature|credential|jwt|password|email|phone|user)", re.I)


def compact(value: Any, limit: int = 1200):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()[:limit]
    return None


def safe_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = {"searches": []}
    for search in payload.get("searches", []):
        if not isinstance(search, dict):
            continue
        node = {}
        for key, value in search.items():
            if key in SAFE_SEARCH_KEYS and not SENSITIVE.search(key) and isinstance(value, (str, int, float, bool)):
                node[key] = compact(value)
        out["searches"].append(node)
    return out


def public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in doc.items():
        key = str(key)
        if key not in SAFE_DOC_KEYS or SENSITIVE.search(key):
            continue
        val = compact(value, 900)
        if val is not None:
            out[key] = val
    return out


def extract_docs(data: Any) -> list[dict[str, Any]]:
    docs = []
    if not isinstance(data, dict):
        return docs
    for result in data.get("results", []):
        if not isinstance(result, dict):
            continue
        for hit in result.get("hits", [])[:500]:
            if isinstance(hit, dict) and isinstance(hit.get("document"), dict):
                doc = public_doc(hit["document"])
                if doc:
                    docs.append(doc)
    return docs


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for row in rows:
        key = (
            str(row.get("lot_id") or row.get("id") or ""),
            str(row.get("auction_id") or ""),
            str(row.get("title") or row.get("name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def local_scope_hint(payload: dict[str, Any]) -> str:
    bits = []
    for search in payload.get("searches", []):
        if isinstance(search, dict):
            bits.append(str(search.get("filter_by", "")))
    return " | ".join(bits)


def run() -> int:
    report: dict[str, Any] = {
        "schema": "macbid-direct-hunt-v1",
        "source": LOCATION_PAGE,
        "privacy": {
            "public_catalog_only": True,
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "typesense_api_key_persisted": False,
            "account_state_captured": False,
        },
        "contract": None,
        "scope_hint": None,
        "searches": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1300})
        page = context.new_page()

        candidates: list[tuple[str, dict[str, Any]]] = []

        def on_request(request: Request):
            if "typesense.net/multi_search" not in request.url:
                return
            try:
                payload = request.post_data_json
            except Exception:
                return
            if isinstance(payload, dict) and isinstance(payload.get("searches"), list):
                candidates.append((request.url, payload))

        page.on("request", on_request)
        nav = page.goto(LOCATION_PAGE, wait_until="domcontentloaded", timeout=60_000)
        report["navigation_status"] = nav.status if nav else None
        page.wait_for_timeout(5_000)

        if not candidates:
            raise RuntimeError("No public Typesense multi_search contract observed")

        # Prefer the contract whose filter visibly encodes the local location page.
        selected_url, selected_payload = candidates[-1]
        for raw_url, payload in candidates:
            hint = local_scope_hint(payload).lower()
            if "san antonio" in hint or "schertz" in hint:
                selected_url, selected_payload = raw_url, payload
                break

        report["contract"] = safe_search_payload(selected_payload)
        report["scope_hint"] = compact(local_scope_hint(selected_payload), 3000)
        report["typesense_host"] = urlsplit(selected_url).hostname or ""
        print("DIRECT_CONTRACT " + json.dumps({"host": report["typesense_host"], "scope_hint": report["scope_hint"], "contract": report["contract"]}, sort_keys=True))

        # Keep the public search-only API key strictly in runner memory as part of
        # the browser-observed URL. It is never printed or written to the artifact.
        for term in TERMS:
            payload = copy.deepcopy(selected_payload)
            for search in payload.get("searches", []):
                if not isinstance(search, dict):
                    continue
                search["q"] = term
                # Ask for enough public hits to cover the local candidate set while
                # retaining the location page's original filters/facets.
                if isinstance(search.get("per_page"), int):
                    search["per_page"] = min(max(search["per_page"], 100), 250)
                elif "per_page" not in search:
                    search["per_page"] = 100
                search["page"] = 1

            node = {"term": term, "lots": [], "status": None}
            report["searches"].append(node)
            try:
                response = context.request.post(
                    selected_url,
                    data=json.dumps(payload),
                    headers={"content-type": "application/json"},
                    timeout=30_000,
                )
                node["status"] = response.status
                data = response.json()
                node["lots"] = dedupe(extract_docs(data))
                print("DIRECT_SEARCH " + json.dumps({"term": term, "status": node["status"], "lots": len(node["lots"])}, sort_keys=True))
                for lot in node["lots"][:100]:
                    print("DIRECT_LOT " + json.dumps(lot, sort_keys=True))
            except Exception as exc:
                node["error"] = f"{type(exc).__name__}: {exc}"
                print(f"DIRECT_SEARCH_ERROR term={term!r} error={node['error']}")

        context.close()
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"DIRECT_HUNT_REPORT={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
