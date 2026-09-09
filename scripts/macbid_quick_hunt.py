from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Response, sync_playwright

OUTPUT = Path("results/macbid-quick-hunt.json")
TERMS = ("Kwikset", "Schlage", "Aqara", "smart lock", "Chamberlain")
TARGETS = ("San Antonio", "Schertz")
SAFE_KEYS = {
    "id", "lot_id", "lot_number", "auction_id", "auction_number", "title", "name",
    "condition", "condition_name", "retail_price", "retail", "current_bid", "current_price",
    "price", "end_time", "closing_date", "closing_date_utc", "location_id", "location_name",
    "building_id", "building_name", "city_state", "code", "upc", "asin", "model",
    "model_number", "manufacturer", "brand", "stock_image_url", "slug", "url", "is_open",
    "status", "total_bids", "unique_bidders", "watchers_count", "box_size"
}
SENSITIVE = re.compile(r"(?:token|auth|cookie|session|secret|api.?key|signature|credential|jwt|password|email|phone|user)", re.I)


def clean(v: Any):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip()[:800]
    return None


def public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in doc.items():
        k = str(k)
        if k not in SAFE_KEYS or SENSITIVE.search(k):
            continue
        val = clean(v)
        if val is not None:
            out[k] = val
    return out


def docs_from_typesense(response: Response) -> list[dict[str, Any]]:
    if "typesense.net/multi_search" not in response.url:
        return []
    try:
        data = response.json()
    except Exception:
        return []
    docs = []
    for result in data.get("results", []) if isinstance(data, dict) else []:
        if not isinstance(result, dict):
            continue
        for hit in result.get("hits", [])[:250]:
            if not isinstance(hit, dict) or not isinstance(hit.get("document"), dict):
                continue
            doc = public_doc(hit["document"])
            if doc:
                docs.append(doc)
    return docs


def is_target(doc: dict[str, Any]) -> bool:
    loc = " ".join(str(doc.get(k, "")) for k in ("location_name", "building_name", "city_state", "code")).lower()
    if not loc:
        return True
    return "san antonio" in loc or "schertz" in loc or re.search(r"\bsa[ab]\b|\bsz[abl]\b", loc) is not None


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for row in rows:
        key = (str(row.get("lot_id") or row.get("id") or ""), str(row.get("auction_id") or ""), str(row.get("title") or row.get("name") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def run() -> int:
    report = {
        "schema": "macbid-quick-hunt-v1",
        "target_pickups": list(TARGETS),
        "privacy": {
            "public_catalog_only": True,
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "typesense_api_key_captured": False,
            "account_state_captured": False,
        },
        "searches": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1400}, locale="en-US")
        active: dict[str, Any] | None = None
        capture = False

        def on_response(response: Response):
            nonlocal active, capture
            if not capture or active is None:
                return
            rows = docs_from_typesense(response)
            if rows:
                active["captured_docs"].extend(rows)

        page.on("response", on_response)

        for term in TERMS:
            node = {"term": term, "pickup_scope": {}, "captured_docs": [], "lots": []}
            report["searches"].append(node)
            active = node
            capture = False
            try:
                nav = page.goto("https://www.mac.bid/search?q=" + term.replace(" ", "%20"), wait_until="domcontentloaded", timeout=60_000)
                node["navigation_status"] = nav.status if nav else None
                page.wait_for_timeout(2200)

                # Capture only responses caused by our explicit local refinements.
                capture = True
                for target in TARGETS:
                    box = page.locator(f'input.ais-RefinementList-checkbox[value="{target}"]').first
                    try:
                        box.wait_for(state="attached", timeout=8_000)
                        if not box.is_checked():
                            box.click()
                            page.wait_for_timeout(1200)
                        node["pickup_scope"][target] = box.is_checked()
                    except Exception as exc:
                        node["pickup_scope"][target] = type(exc).__name__
                page.wait_for_timeout(2200)
                capture = False

                target_rows = [row for row in node["captured_docs"] if is_target(row)]
                node["lots"] = dedupe(target_rows)
                node["captured_docs"] = []
                node["body_excerpt"] = re.sub(r"\s+", " ", page.locator("body").inner_text()).strip()[:1400]
                print("QUICK_HUNT " + json.dumps({"term": term, "scope": node["pickup_scope"], "lots": len(node["lots"])}, sort_keys=True))
                for lot in node["lots"][:80]:
                    print("QUICK_LOT " + json.dumps(lot, sort_keys=True))
            except Exception as exc:
                capture = False
                node["error"] = f"{type(exc).__name__}: {exc}"
                print(f"QUICK_HUNT_ERROR term={term!r} error={node['error']}")
            finally:
                active = None

        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"QUICK_HUNT_REPORT={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
