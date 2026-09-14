from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

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
    source = cfg["source"]["cars_com"]
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 compatible; Scraper-Public vehicle research"})
    cards: list[dict] = []
    seen: set[str] = set()
    for page_number in range(1, int(source.get("pages", 3)) + 1):
        response = session.get(cars_url(cfg, page_number), timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        nodes = soup.select(".vehicle-card, [data-listing-id]")
        if not nodes:
            break
        for node in nodes:
            text = node.get_text("\n", strip=True)
            if "Toyota RAV4" not in text:
                continue
            link = node.select_one('a[href*="/vehicledetail/"]') or node.select_one("a[href]")
            image = node.select_one("img")
            url = link.get("href") if link else None
            if url and url.startswith("/"):
                url = "https://www.cars.com" + url
            image_url = None
            if image:
                image_url = image.get("src") or image.get("data-src")
            key = url or text[:160]
            if key in seen:
                continue
            seen.add(key)
            cards.append({"text": text, "url": url, "image_url": image_url})
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
    unique = {listing_key(row): row for row in rows}
    rows = list(unique.values())
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
