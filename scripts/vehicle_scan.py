from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from vehicle_engine.identity import dedupe_rows
from vehicle_engine.normalize import parse_autotrader_card, parse_dealer_detail
from vehicle_engine.scoring import rank_vehicles

CONFIG = Path("config/vehicle_hunt.json")
RESULT = Path("results/vehicle-hunt.json")
PREVIOUS = Path("results/vehicle-previous.json")


def load_config(path: Path) -> tuple[dict, dict]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    policy = {**cfg["market"], **cfg["vehicle"], **cfg["ownership_cost"]}
    return cfg, policy


def configured_dealers(cfg: dict) -> list[dict]:
    source = cfg.get("source", {})
    return [
        *list(source.get("local_dealers", [])),
        *list(source.get("nearby_dealers", [])),
    ]


def configured_aggregators(cfg: dict) -> list[dict]:
    return [row for row in cfg.get("source", {}).get("aggregators", []) if row.get("enabled", True)]


def _looks_like_challenge(status: int | None, title: str, body: str) -> bool:
    if status is not None and status >= 400:
        return True
    haystack = f"{title}\n{body[:1600]}".lower()
    return any(token in haystack for token in (
        "access denied", "verify you are human", "captcha", "just a moment",
        "request blocked", "security challenge",
    ))


def _discover_detail_links(page, dealer: dict) -> list[str]:
    patterns = [str(value) for value in dealer.get("detail_url_contains", [])]
    inventory_url = str(dealer["inventory_url"])
    rows = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map((a) => {
          const box = a.closest('article, li, [data-vehicle], [data-vin], .vehicle-card, .inventory-item, .vehicle, .vehicle-item');
          return {
            href: a.href || '',
            text: (a.innerText || a.textContent || '').trim().slice(0, 220),
            context: box ? (box.innerText || '').trim().slice(0, 900) : ''
          };
        })
        """
    )
    links: list[str] = []
    seen: set[str] = set()
    for row in rows:
        href = str(row.get("href") or "").strip()
        if not href or href == inventory_url:
            continue
        context = f"{row.get('text') or ''} {row.get('context') or ''} {href}".lower()
        if "rav4" not in context:
            continue
        if patterns and not any(pattern.lower() in href.lower() for pattern in patterns):
            continue
        absolute = urljoin(inventory_url, href).split("#", 1)[0]
        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return links


def fetch_local_dealers(cfg: dict) -> tuple[list[dict], dict[str, str]]:
    """Render configured local/nearby dealer inventory and normalize detail pages."""
    from playwright.sync_api import sync_playwright

    dealers = configured_dealers(cfg)
    rows: list[dict] = []
    errors: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
        )
        inventory_page = context.new_page()
        detail_page = context.new_page()

        for dealer in dealers:
            source_id = str(dealer.get("id") or "unknown_dealer")
            try:
                response = inventory_page.goto(
                    str(dealer["inventory_url"]), wait_until="domcontentloaded", timeout=60000
                )
                status = response.status if response else None
                inventory_page.wait_for_timeout(3000)
                title = inventory_page.title()
                body = inventory_page.locator("body").inner_text(timeout=15000)
                if _looks_like_challenge(status, title, body):
                    raise RuntimeError(f"inventory blocked status={status} title={title!r}")

                links = _discover_detail_links(inventory_page, dealer)
                print(f"VEHICLE_SOURCE_PAGE source={source_id} status={status} detail_links={len(links)}")
                if not links:
                    raise RuntimeError("no RAV4 detail links discovered")

                parsed_count = 0
                failed_count = 0
                for url in links[:40]:
                    try:
                        detail_response = detail_page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        detail_status = detail_response.status if detail_response else None
                        detail_page.wait_for_timeout(900)
                        detail_title = detail_page.title()
                        detail_text = detail_page.locator("body").inner_text(timeout=12000)
                        if _looks_like_challenge(detail_status, detail_title, detail_text):
                            failed_count += 1
                            continue
                        image_url = detail_page.locator('meta[property="og:image"]').get_attribute("content") \
                            if detail_page.locator('meta[property="og:image"]').count() else None
                        row = parse_dealer_detail(
                            {"text": detail_text, "url": detail_page.url, "image_url": image_url}, dealer
                        )
                        if row:
                            rows.append(row)
                            parsed_count += 1
                        else:
                            failed_count += 1
                    except Exception:
                        failed_count += 1
                print(
                    f"VEHICLE_SOURCE_DETAIL source={source_id} parsed={parsed_count} failed={failed_count}"
                )
                if parsed_count == 0:
                    errors[source_id] = "detail_pages_discovered_but_none_parsed"
            except Exception as exc:
                errors[source_id] = f"{type(exc).__name__}: {exc}"
                print(f"VEHICLE_SOURCE_DEGRADED source={source_id} reason={errors[source_id]}")

        context.close()
        browser.close()

    return rows, errors


def _autotrader_cards(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const anchors = Array.from(document.querySelectorAll('a[href*="/cars-for-sale/inventory/"]'));
          const out = [];
          const seen = new Set();
          for (const a of anchors) {
            const href = (a.href || '').split('#')[0];
            if (!href || seen.has(href)) continue;
            let node = a;
            let best = null;
            for (let i = 0; node && i < 8; i++, node = node.parentElement) {
              const text = (node.innerText || '').trim();
              if (/20\d{2}\s+Toyota\s+RAV4/i.test(text) && /\b(?:mi|miles)\b/i.test(text) && text.length < 2600) {
                best = node;
              }
            }
            if (!best) continue;
            const text = (best.innerText || '').trim();
            const img = best.querySelector('img[src]');
            seen.add(href);
            out.push({href, text, image_url: img ? img.src : null});
          }
          return out;
        }
        """
    )


def fetch_aggregators(cfg: dict) -> tuple[list[dict], dict[str, str]]:
    """Best-effort discovery enrichment. Never required for dealer-direct refresh success."""
    from playwright.sync_api import sync_playwright

    rows: list[dict] = []
    errors: dict[str, str] = {}
    sources = configured_aggregators(cfg)
    if not sources:
        return rows, errors

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1400},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        for source in sources:
            source_id = str(source.get("id") or source.get("kind") or "aggregator")
            try:
                response = page.goto(str(source["inventory_url"]), wait_until="domcontentloaded", timeout=60000)
                status = response.status if response else None
                page.wait_for_timeout(2500)
                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(900)
                title = page.title()
                body = page.locator("body").inner_text(timeout=15000)
                if _looks_like_challenge(status, title, body):
                    raise RuntimeError(f"aggregator blocked status={status} title={title!r}")

                cards = _autotrader_cards(page) if source.get("kind") == "autotrader" else []
                parsed_count = 0
                max_cards = int(source.get("max_cards") or 60)
                for card in cards[:max_cards]:
                    parsed = parse_autotrader_card(
                        {"text": card.get("text"), "url": card.get("href"), "image_url": card.get("image_url")},
                        source,
                    )
                    if parsed:
                        rows.append(parsed)
                        parsed_count += 1
                print(f"VEHICLE_AGGREGATOR source={source_id} status={status} cards={len(cards)} parsed={parsed_count}")
                if parsed_count == 0:
                    errors[source_id] = "no parseable aggregator cards"
            except Exception as exc:
                errors[source_id] = f"{type(exc).__name__}: {exc}"
                print(f"VEHICLE_AGGREGATOR_DEGRADED source={source_id} reason={errors[source_id]}")
        context.close()
        browser.close()
    return rows, errors


def listing_key(row: dict) -> str:
    return str(row.get("vin") or row.get("source_url") or f"{row.get('year')}|{row.get('title')}|{row.get('dealer')}")


def add_history(rows: list[dict], previous_path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    previous = {}
    if previous_path.exists():
        try:
            old = json.loads(previous_path.read_text(encoding="utf-8"))
            previous = {listing_key(row): row for row in old.get("vehicles", [])}
        except Exception:
            previous = {}
    for row in rows:
        old = previous.get(listing_key(row), {})
        old_price = old.get("price")
        row["first_seen_utc"] = old.get("first_seen_utc") or now
        row["last_seen_utc"] = now
        row["previous_price"] = old_price
        row["price_delta"] = row["price"] - old_price if isinstance(old_price, (int, float)) else None


def source_registry(cfg: dict) -> list[dict]:
    fields = (
        "id", "name", "location", "market_local", "locality_hint", "area_priority",
        "inventory_url", "doc_fee", "mandatory_addon_amount", "addon_warning", "role",
    )
    sources = [*configured_dealers(cfg), *configured_aggregators(cfg)]
    return [
        {key: source.get(key) for key in fields if source.get(key) is not None}
        for source in sources
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--previous", default=str(PREVIOUS))
    parser.add_argument("--output", default=str(RESULT))
    args = parser.parse_args()

    cfg, policy = load_config(Path(args.config))
    dealer_rows, dealer_errors = fetch_local_dealers(cfg)
    aggregator_rows, aggregator_errors = fetch_aggregators(cfg)
    raw_rows = [*dealer_rows, *aggregator_rows]
    source_observations = dict(sorted(Counter(str(row.get("source") or "unknown") for row in raw_rows).items()))
    rows = dedupe_rows(raw_rows)
    if not rows:
        raise RuntimeError("all configured vehicle sources returned zero parseable RAV4 listings")

    add_history(rows, Path(args.previous))
    ranked = rank_vehicles(rows, policy)
    source_counts = dict(sorted(Counter(str(row.get("source") or "unknown") for row in rows).items()))
    source_errors = {**dealer_errors, **aggregator_errors}

    payload = {
        "schema": "vehicle-hunt-catalog-v1",
        "generated_epoch_utc": int(time.time()),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "market": cfg["market"],
        "query": cfg["vehicle"],
        "ownership_cost": cfg["ownership_cost"],
        "source_registry": source_registry(cfg),
        "discovery_routes": list(cfg.get("source", {}).get("discovery_routes", [])),
        "source_observations": source_observations,
        "source_counts": source_counts,
        "source_errors": source_errors,
        "raw_listing_count": len(raw_rows),
        "deduped_listing_count": len(rows),
        "eligible_count": len(ranked),
        "vehicles": ranked,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(f"VEHICLE_MARKET={cfg['market']['label']} zip={cfg['market']['zip']}")
    print(f"VEHICLE_LOCALITY preferred={cfg['market']['preferred_radius_miles']} hard={cfg['market']['hard_radius_miles']}")
    print(f"VEHICLE_SOURCE_OBSERVATIONS={json.dumps(source_observations, sort_keys=True)}")
    print(f"VEHICLE_SOURCES={json.dumps(source_counts, sort_keys=True)}")
    print(f"VEHICLE_SOURCE_ERRORS={json.dumps(source_errors, sort_keys=True)}")
    print(f"VEHICLE_DISCOVERY_ROUTES={len(payload['discovery_routes'])}")
    print(f"VEHICLE_RAW={len(raw_rows)} deduped={len(rows)} eligible={len(ranked)}")
    for row in ranked[:15]:
        print(json.dumps({key: row.get(key) for key in (
            "rank", "title", "dealer", "price", "mileage", "locality", "area_priority",
            "deal_score", "estimated_otd", "dealer_mandatory_addon_amount", "source_url", "sources"
        )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
