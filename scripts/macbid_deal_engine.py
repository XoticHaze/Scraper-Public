from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Request, sync_playwright

from deal_engine.scoring import score_lot

LOCATION_PAGE = "https://www.mac.bid/locations/san-antonio"
CONFIG_PATH = Path("config/macbid_deal_engine.json")
OUTPUT = Path("results/macbid-deal-engine.json")

SAFE_DOC_KEYS = {
    "id", "lot_id", "lot_number", "inventory_id", "auction_id", "auction_number",
    "auction_title", "auction_location", "product_name", "title", "name", "description",
    "condition", "condition_name", "retail_price", "retail", "current_bid", "current_price",
    "price", "expected_close_date", "end_time", "closing_date", "closing_date_utc",
    "pickup_date", "location_id", "location_name", "building_id", "building_name", "city_state",
    "code", "upc", "asin", "model", "model_number", "manufacturer", "brand", "stock_image_url",
    "image_url", "slug", "url", "is_open", "status", "total_bids", "unique_bidders",
    "watchers_count", "box_size", "category", "ranking_weight"
}
SENSITIVE = re.compile(
    r"(?:token|auth|cookie|session|secret|api.?key|signature|credential|jwt|password|email|phone|user)",
    re.I,
)


def compact(value: Any, limit: int = 1400):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()[:limit]
    return None


def public_doc(doc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in doc.items():
        key = str(key)
        if key not in SAFE_DOC_KEYS or SENSITIVE.search(key):
            continue
        clean = compact(value, 900)
        if clean is not None:
            out[key] = clean
    auction = out.get("auction_number")
    lot = out.get("lot_number")
    if auction and lot:
        out["macbid_url"] = f"https://www.mac.bid/auction/{auction}/lot/{lot}"
    return out


def extract_docs(data: Any) -> tuple[list[dict[str, Any]], int | None]:
    if not isinstance(data, dict):
        return [], None
    results = data.get("results", [])
    if not results or not isinstance(results[0], dict):
        return [], None
    result = results[0]
    docs: list[dict[str, Any]] = []
    for hit in result.get("hits", []):
        if isinstance(hit, dict) and isinstance(hit.get("document"), dict):
            doc = public_doc(hit["document"])
            if doc:
                docs.append(doc)
    found = result.get("found")
    return docs, int(found) if isinstance(found, int) else None


def dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for row in rows:
        key = (
            str(row.get("lot_id") or row.get("id") or ""),
            str(row.get("auction_id") or ""),
            str(row.get("lot_number") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def local_contract(payload: dict[str, Any]) -> dict[str, Any] | None:
    searches = payload.get("searches", []) if isinstance(payload, dict) else []
    for search in searches:
        if not isinstance(search, dict):
            continue
        filter_by = str(search.get("filter_by", ""))
        if "auction_location" in filter_by and "is_open:=1" in filter_by:
            return copy.deepcopy(search)
    return None


def list_filter(field: str, values: list[str]) -> str:
    escaped = [str(value).replace("`", "") for value in values]
    rendered = ",".join(f"`{value}`" for value in escaped)
    return f"{field}:=[{rendered}]"


def catalog_filter(locations: list[str], conditions: list[str], min_retail: float) -> str:
    return " && ".join(
        [
            "is_open:=1",
            list_filter("auction_location", locations),
            list_filter("condition", conditions),
            f"retail_price:>={min_retail:g}",
        ]
    )


def condition_rank(condition: str, config: dict[str, Any]) -> int:
    ranking = config.get("condition_priority", {})
    try:
        return int(ranking.get(condition.upper(), 999))
    except Exception:
        return 999


def close_date_key(lot: dict[str, Any]) -> str:
    value = lot.get("expected_close_date")
    return str(value) if value else "9999-12-31"


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    locations = [str(v) for v in config["locations"]]
    preferred_condition_list = [str(v).upper() for v in config["preferred_conditions"]]
    preferred_conditions = set(preferred_condition_list)
    excluded_conditions = {str(v).upper() for v in config["excluded_conditions"]}
    min_retail = float(config["minimum_stated_retail"])
    premium_rate = float(config["buyer_premium_rate"])
    lot_fee = float(config["lot_fee"])

    report: dict[str, Any] = {
        "schema": "macbid-deal-engine-v2",
        "source": LOCATION_PAGE,
        "policy": config,
        "privacy": {
            "public_catalog_only": True,
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "typesense_api_key_persisted": False,
            "account_state_captured": False
        },
        "scan": {},
        "inventory": [],
        "views": {},
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
        report["scan"]["bootstrap_status"] = nav.status if nav else None
        page.wait_for_timeout(4_000)
        if not candidates:
            raise RuntimeError("No public Typesense search contract observed")

        selected_url = None
        selected_search = None
        for raw_url, payload in candidates:
            search = local_contract(payload)
            if search is not None:
                selected_url, selected_search = raw_url, search
                break
        if selected_url is None or selected_search is None:
            raise RuntimeError("No local MAC.BID search contract observed")

        selected_search["q"] = "*"
        selected_search["filter_by"] = catalog_filter(locations, preferred_condition_list, min_retail)
        selected_search["sort_by"] = "expected_close_date:asc"
        selected_search["per_page"] = 250
        selected_search["page"] = 1

        report["scan"]["typesense_host"] = urlsplit(selected_url).hostname or ""
        report["scan"]["filter_by"] = selected_search["filter_by"]
        report["scan"]["sort_by"] = selected_search["sort_by"]

        all_docs: list[dict[str, Any]] = []
        page_num = 1
        total_found = None
        max_pages = 200
        while page_num <= max_pages:
            search = copy.deepcopy(selected_search)
            search["page"] = page_num
            payload = {"searches": [search]}
            response = context.request.post(
                selected_url,
                data=json.dumps(payload),
                headers={"content-type": "application/json"},
                timeout=30_000,
            )
            if response.status != 200:
                raise RuntimeError(f"Typesense search failed with HTTP {response.status}: {response.text()[:500]}")
            docs, found = extract_docs(response.json())
            if total_found is None:
                total_found = found
            all_docs.extend(docs)
            print(f"DEAL_SCAN_PAGE page={page_num} docs={len(docs)} found={found}")
            if len(docs) < int(search["per_page"]):
                break
            page_num += 1
        if page_num > max_pages:
            raise RuntimeError(f"Catalog exceeded safety cap of {max_pages * 250} preferred lots")

        context.close()
        browser.close()

    inventory = dedupe(all_docs)
    report["scan"]["reported_found"] = total_found
    report["scan"]["pages_scanned"] = page_num
    report["scan"]["deduped_inventory"] = len(inventory)
    if total_found is not None:
        report["scan"]["complete"] = len(inventory) >= total_found

    eligible: list[dict[str, Any]] = []
    excluded_counts: dict[str, int] = {}
    for lot in inventory:
        condition = str(lot.get("condition") or "").upper()
        retail = lot.get("retail_price") if lot.get("retail_price") is not None else lot.get("retail")
        try:
            retail_num = float(retail)
        except (TypeError, ValueError):
            retail_num = None

        reason = None
        if condition in excluded_conditions:
            reason = "excluded_condition"
        elif condition not in preferred_conditions:
            reason = "non_preferred_condition"
        elif retail_num is None or retail_num < min_retail:
            reason = "low_or_missing_stated_retail"

        if reason:
            excluded_counts[reason] = excluded_counts.get(reason, 0) + 1
            continue

        scored = dict(lot)
        scored.update(
            score_lot(
                lot,
                premium_rate=premium_rate,
                lot_fee=lot_fee,
                low_value_retail_floor=min_retail,
            )
        )
        eligible.append(scored)

    report["scan"]["eligible_inventory"] = len(eligible)
    report["scan"]["excluded_counts"] = excluded_counts
    report["inventory"] = eligible

    # Typesense gives us the correct close *date*. Exact within-day time is a
    # separate public lot-state enrichment step; never invent midnight.
    ending_soon = sorted(
        eligible,
        key=lambda x: (
            close_date_key(x),
            condition_rank(str(x.get("condition") or ""), config),
            -float(x.get("deal_score") or 0),
        ),
    )
    best_value = sorted(
        eligible,
        key=lambda x: (
            -float(x.get("deal_score") or 0),
            condition_rank(str(x.get("condition") or ""), config),
            close_date_key(x),
        ),
    )
    low_competition = sorted(
        eligible,
        key=lambda x: (
            int(x.get("unique_bidders") or 0),
            int(x.get("total_bids") or 0),
            -float(x.get("deal_score") or 0),
            close_date_key(x),
        ),
    )

    limits = config.get("views", {})
    report["views"] = {
        "ending_soon": ending_soon[: int(limits.get("ending_soon", 100))],
        "best_value": best_value[: int(limits.get("best_value", 100))],
        "low_competition": low_competition[: int(limits.get("low_competition", 100))],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"DEAL_ENGINE_INVENTORY={len(inventory)}")
    print(f"DEAL_ENGINE_ELIGIBLE={len(eligible)}")
    print(f"DEAL_ENGINE_COMPLETE={report['scan'].get('complete')}")
    for name, rows in report["views"].items():
        print(f"DEAL_VIEW {name} count={len(rows)}")
        for lot in rows[:20]:
            print(
                "DEAL_LOT "
                + json.dumps(
                    {
                        "view": name,
                        "product_name": lot.get("product_name") or lot.get("title") or lot.get("name"),
                        "auction_location": lot.get("auction_location"),
                        "condition": lot.get("condition"),
                        "current_bid": lot.get("current_bid"),
                        "retail_price": lot.get("retail_price"),
                        "estimated_pre_tax_total": lot.get("estimated_pre_tax_total"),
                        "deal_score": lot.get("deal_score"),
                        "expected_close_date": lot.get("expected_close_date"),
                        "unique_bidders": lot.get("unique_bidders"),
                        "lot_number": lot.get("lot_number"),
                        "auction_number": lot.get("auction_number"),
                        "macbid_url": lot.get("macbid_url"),
                    },
                    sort_keys=True,
                )
            )
    print(f"DEAL_ENGINE_REPORT={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
