from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from vehicle_engine.normalize import parse_cars_com_card
from vehicle_engine.scoring import rank_vehicles

CONFIG = Path("config/vehicle_hunt.json")
RESULT = Path("results/vehicle-hunt.json")
PREVIOUS = Path("results/vehicle-previous.json")


def load_config(path: Path) -> tuple[dict, dict]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    policy = {**cfg["market"], **cfg["vehicle"], **cfg["ownership_cost"]}
    return cfg, policy


def cars_url(cfg: dict, page: int) -> str:
    market = cfg["market"]
    vehicle = cfg["vehicle"]
    source = cfg["source"]["cars_com"]
    params = {
        "stock_type": "used",
        "makes[]": vehicle["make"].lower(),
        "models[]": f"{vehicle['make'].lower()}-{vehicle['model'].lower()}",
        "maximum_distance": source.get("maximum_distance_query_miles", 250),
        "zip": market["zip"],
        "year_min": vehicle["year_min"],
        "year_max": vehicle["year_max"],
        "list_price_max": vehicle["max_price"],
        "page": page,
    }
    return "https://www.cars.com/shopping/results/?" + urlencode(params, doseq=True)


def fetch_cards(cfg: dict) -> list[dict]:
    """Fetch rendered public result cards through Chromium.

    Cars.com rejects raw datacenter HTTP requests with 403, while the existing
    deal workflow already provisions Playwright/Chromium for browser smoke
    tests. Reusing that browser path keeps the source adapter public-only and
    avoids adding credentials or a second execution surface.
    """
    from playwright.sync_api import sync_playwright

    source = cfg["source"]["cars_com"]
    max_pages = int(source.get("pages", 3))
    cards: list[dict] = []
    seen: set[str] = set()

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
        page = context.new_page()

        for page_number in range(1, max_pages + 1):
            url = cars_url(cfg, page_number)
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            status = response.status if response else None
            page.wait_for_timeout(2500)

            title = page.title()
            body_text = page.locator("body").inner_text(timeout=10000)[:1000]
            if status and status >= 400:
                raise RuntimeError(f"cars.com browser status {status}")
            if "access denied" in body_text.lower() or "verify you are human" in body_text.lower():
                raise RuntimeError(f"cars.com browser challenge: {title}")

            extracted = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('.vehicle-card, [data-listing-id]'))
                  .map((el) => {
                    const a = el.querySelector('a[href*="/vehicledetail/"]') || el.querySelector('a[href]');
                    const img = el.querySelector('img');
                    return {
                      text: (el.innerText || '').trim(),
                      url: a ? a.href : null,
                      image_url: img ? (img.currentSrc || img.src || null) : null,
                    };
                  })
                  .filter((x) => x.text && /20\d{2}\s+Toyota\s+RAV4/i.test(x.text));
                """
            )
            print(f"VEHICLE_SOURCE_PAGE source=cars.com page={page_number} status={status} cards={len(extracted)}")
            if not extracted:
                if page_number == 1:
                    raise RuntimeError("cars.com rendered zero RAV4 cards")
                break

            for card in extracted:
                key = card.get("url") or card.get("text", "")[:160]
                if key and key not in seen:
                    seen.add(key)
                    cards.append(card)

        context.close()
        browser.close()

    return cards


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--previous", default=str(PREVIOUS))
    parser.add_argument("--output", default=str(RESULT))
    args = parser.parse_args()

    cfg, policy = load_config(Path(args.config))
    parsed = [parse_cars_com_card(card) for card in fetch_cards(cfg)]
    rows = [row for row in parsed if row]
    rows = list({listing_key(row): row for row in rows}.values())
    if not rows:
        raise RuntimeError("vehicle source returned no parseable listings")

    add_history(rows, Path(args.previous))
    ranked = rank_vehicles(rows, policy)

    payload = {
        "schema": "vehicle-hunt-catalog-v1",
        "generated_epoch_utc": int(time.time()),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "market": cfg["market"],
        "query": cfg["vehicle"],
        "ownership_cost": cfg["ownership_cost"],
        "source_counts": {"cars.com": len(rows)},
        "raw_listing_count": len(rows),
        "eligible_count": len(ranked),
        "vehicles": ranked,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"VEHICLE_MARKET={cfg['market']['label']} zip={cfg['market']['zip']}")
    print(f"VEHICLE_LOCALITY preferred={cfg['market']['preferred_radius_miles']} hard={cfg['market']['hard_radius_miles']}")
    print(f"VEHICLE_RAW={len(rows)} eligible={len(ranked)}")
    for row in ranked[:15]:
        print(json.dumps({key: row.get(key) for key in ("rank", "title", "price", "mileage", "distance_miles", "locality", "deal_score", "estimated_otd", "source_url")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
