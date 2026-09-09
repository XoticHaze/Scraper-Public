from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Request, Response, sync_playwright

SEARCH_URL = "https://www.mac.bid/search?q={query}"
OUTPUT = Path("results/macbid-live-hunt.json")

TERMS = (
    "Kwikset",
    "Schlage",
    "Yale lock",
    "Aqara",
    "Z-Wave",
    "Zigbee",
    "Matter",
    "Thread",
    "HomeKit",
    "smart lock",
    "smart switch",
    "smart sensor",
    "smart thermostat",
    "Chamberlain",
    "LiftMaster",
)

TARGET_PICKUPS = ("San Antonio", "Schertz")

SENSITIVE_KEY_RE = re.compile(
    r"(?:token|auth|authorization|cookie|session|secret|api.?key|signature|credential|jwt|password|email|phone|user)",
    re.IGNORECASE,
)

SAFE_QUERY_KEYS = {
    "q",
    "query_by",
    "filter_by",
    "sort_by",
    "facet_by",
    "max_facet_values",
    "page",
    "per_page",
    "highlight_fields",
    "include_fields",
    "exclude_fields",
    "num_typos",
    "prefix",
    "typo_tokens_threshold",
}

SAFE_LOT_KEYS = {
    "id",
    "lot_id",
    "lot_number",
    "auction_id",
    "auction_number",
    "auction_slug",
    "auction_title",
    "title",
    "name",
    "description",
    "condition",
    "condition_name",
    "box_size",
    "retail_price",
    "retail",
    "current_bid",
    "current_price",
    "price",
    "end_time",
    "closing_date",
    "closing_date_utc",
    "pickup_date",
    "location_id",
    "location_name",
    "building_id",
    "building_name",
    "city_state",
    "code",
    "upc",
    "asin",
    "model",
    "model_number",
    "manufacturer",
    "brand",
    "stock_image_url",
    "image_url",
    "slug",
    "url",
    "is_open",
    "status",
    "total_bids",
    "unique_bidders",
    "watchers_count",
}


def compact(value: Any, limit: int = 800) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()[:limit]
    return None


def safe_public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in doc.items():
        key_s = str(key)
        if SENSITIVE_KEY_RE.search(key_s):
            continue
        if key_s not in SAFE_LOT_KEYS:
            continue
        clean = compact(value)
        if clean is not None:
            out[key_s] = clean
    return out


def sanitize_typesense_request(request: Request) -> dict[str, Any] | None:
    if "typesense.net/multi_search" not in request.url:
        return None
    try:
        payload = request.post_data_json
    except Exception:
        return {"host": urlsplit(request.url).hostname or "", "searches": []}
    if not isinstance(payload, dict):
        return {"host": urlsplit(request.url).hostname or "", "searches": []}
    searches = []
    for node in payload.get("searches", []):
        if not isinstance(node, dict):
            continue
        safe = {}
        for key, value in node.items():
            if key in SAFE_QUERY_KEYS and isinstance(value, (str, int, float, bool)):
                safe[key] = compact(value, 1200)
        searches.append(safe)
    return {"host": urlsplit(request.url).hostname or "", "searches": searches}


def extract_typesense_response(response: Response) -> dict[str, Any] | None:
    if "typesense.net/multi_search" not in response.url:
        return None
    try:
        data = response.json()
    except Exception:
        return {"status": response.status, "results": [], "error": "unreadable_json"}
    if not isinstance(data, dict):
        return {"status": response.status, "results": []}

    results = []
    for result in data.get("results", []):
        if not isinstance(result, dict):
            continue
        node: dict[str, Any] = {}
        for key in ("found", "page", "search_time_ms", "out_of"):
            if key in result and isinstance(result[key], (str, int, float, bool)):
                node[key] = result[key]
        hits = []
        for hit in result.get("hits", [])[:250]:
            if not isinstance(hit, dict):
                continue
            doc = hit.get("document")
            if not isinstance(doc, dict):
                continue
            safe = safe_public_doc(doc)
            if safe:
                hits.append(safe)
        if hits:
            node["hits"] = hits
        # Facet counts are public catalog metadata and help prove the pickup scope.
        facets = []
        for facet in result.get("facet_counts", [])[:30]:
            if not isinstance(facet, dict):
                continue
            field = compact(facet.get("field_name"), 120)
            if not field or SENSITIVE_KEY_RE.search(str(field)):
                continue
            counts = []
            for count in facet.get("counts", [])[:100]:
                if not isinstance(count, dict):
                    continue
                value = compact(count.get("value"), 220)
                qty = count.get("count")
                if value is not None and isinstance(qty, (int, float)):
                    counts.append({"value": value, "count": qty})
            if counts:
                facets.append({"field_name": field, "counts": counts})
        if facets:
            node["facet_counts"] = facets
        results.append(node)
    return {"status": response.status, "results": results}


def pickup_checkbox(page, value: str):
    return page.locator(f'input.ais-RefinementList-checkbox[value="{value}"]').first


def set_pickup_scope(page) -> dict[str, Any]:
    observed = {}
    # The runner geolocates to an arbitrary MAC.BID market. Explicitly clear any
    # selected pickup value except our two target metro locations.
    all_boxes = page.locator("input.ais-RefinementList-checkbox")
    count = all_boxes.count()
    for idx in range(count):
        box = all_boxes.nth(idx)
        try:
            value = box.get_attribute("value") or ""
            checked = box.is_checked()
        except Exception:
            continue
        if checked and value not in TARGET_PICKUPS:
            try:
                box.click()
                page.wait_for_timeout(700)
            except Exception:
                pass

    for value in TARGET_PICKUPS:
        box = pickup_checkbox(page, value)
        try:
            box.wait_for(state="attached", timeout=10_000)
            if not box.is_checked():
                box.click()
                page.wait_for_timeout(1_200)
            observed[value] = box.is_checked()
        except Exception as exc:
            observed[value] = f"{type(exc).__name__}"
    return observed


def dedupe_docs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for doc in docs:
        key = (
            str(doc.get("lot_id") or doc.get("id") or ""),
            str(doc.get("auction_id") or ""),
            str(doc.get("title") or doc.get("name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def run() -> int:
    report: dict[str, Any] = {
        "schema": "macbid-live-hunt-v1",
        "target_pickups": list(TARGET_PICKUPS),
        "terms": [],
        "privacy": {
            "public_catalog_only": True,
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "typesense_api_key_captured": False,
            "account_state_captured": False,
        },
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1400})
        page = context.new_page()

        current: dict[str, Any] | None = None

        def on_request(request: Request) -> None:
            nonlocal current
            if current is None:
                return
            safe = sanitize_typesense_request(request)
            if safe:
                current["typesense_requests"].append(safe)

        def on_response(response: Response) -> None:
            nonlocal current
            if current is None:
                return
            safe = extract_typesense_response(response)
            if safe:
                current["typesense_responses"].append(safe)

        page.on("request", on_request)
        page.on("response", on_response)

        for term in TERMS:
            node: dict[str, Any] = {
                "term": term,
                "typesense_requests": [],
                "typesense_responses": [],
                "pickup_scope": {},
                "lots": [],
            }
            report["terms"].append(node)
            current = node
            try:
                url = SEARCH_URL.format(query=term.replace(" ", "%20"))
                nav = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                node["navigation_status"] = nav.status if nav else None
                page.wait_for_timeout(3_500)
                node["pickup_scope"] = set_pickup_scope(page)
                page.wait_for_timeout(4_500)
                node["final_url"] = page.url

                # Prefer the final Typesense responses after the target facets were applied.
                docs: list[dict[str, Any]] = []
                for response_node in node["typesense_responses"]:
                    for result in response_node.get("results", []):
                        docs.extend(result.get("hits", []))

                # Strong scope guard. If catalog docs expose location/building fields,
                # retain only the San Antonio metro target. If they don't expose one,
                # the checked facet state remains the scope proof in the report.
                scoped = []
                for doc in docs:
                    loc_text = " ".join(
                        str(doc.get(k, ""))
                        for k in ("location_name", "building_name", "city_state", "code")
                    ).lower()
                    if loc_text and not any(x.lower() in loc_text for x in TARGET_PICKUPS):
                        continue
                    scoped.append(doc)
                node["lots"] = dedupe_docs(scoped)
                node["body_excerpt"] = re.sub(
                    r"\s+", " ", page.locator("body").inner_text()
                ).strip()[:1800]
                print(
                    "LIVE_HUNT "
                    + json.dumps(
                        {
                            "term": term,
                            "status": node["navigation_status"],
                            "pickup_scope": node["pickup_scope"],
                            "lots": len(node["lots"]),
                        },
                        sort_keys=True,
                    )
                )
                for lot in node["lots"][:40]:
                    print("LIVE_LOT " + json.dumps(lot, sort_keys=True))
            except Exception as exc:
                node["error"] = f"{type(exc).__name__}: {exc}"
                print(f"LIVE_HUNT_ERROR term={term!r} error={node['error']}")
            finally:
                current = None

        context.close()
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"LIVE_HUNT_REPORT={OUTPUT}")
    print(f"LIVE_HUNT_TERM_COUNT={len(report['terms'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
