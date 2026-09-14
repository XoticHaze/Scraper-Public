from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

from vehicle_engine.normalize import parse_cars_com_card
from vehicle_engine.scoring import rank_vehicles

CONFIG = Path("config/vehicle_hunt.json")
RESULT = Path("results/vehicle-hunt.json")
PREVIOUS = Path("results/vehicle-previous.json")


class VehicleCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.capture_depth: int | None = None
        self.parts: list[str] = []
        self.url: str | None = None
        self.image_url: str | None = None
        self.cards: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = set((attrs_map.get("class") or "").split())
        if self.capture_depth is None and ("vehicle-card" in classes or attrs_map.get("data-listing-id")):
            self.capture_depth = self.depth
            self.parts = []
            self.url = None
            self.image_url = None
        if self.capture_depth is not None:
            href = attrs_map.get("href")
            if tag == "a" and href and "/vehicledetail/" in href and self.url is None:
                self.url = href if href.startswith("http") else "https://www.cars.com" + href
            if tag == "img" and self.image_url is None:
                self.image_url = attrs_map.get("src") or attrs_map.get("data-src")
        self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if self.capture_depth is not None and tag == "img" and self.image_url is None:
            self.image_url = attrs_map.get("src") or attrs_map.get("data-src")

    def handle_data(self, data: str) -> None:
        if self.capture_depth is not None:
            value = data.strip()
            if value:
                self.parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        self.depth = max(0, self.depth - 1)
        if self.capture_depth is not None and self.depth == self.capture_depth:
            text = "\n".join(self.parts)
            if "Toyota RAV4" in text:
                self.cards.append({"text": text, "url": self.url, "image_url": self.image_url})
            self.capture_depth = None
            self.parts = []
            self.url = None
            self.image_url = None


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
    cards: list[dict] = []
    seen: set[str] = set()
    for page_number in range(1, int(source.get("pages", 3)) + 1):
        request = urllib.request.Request(
            cars_url(cfg, page_number),
            headers={"User-Agent": "Mozilla/5.0 compatible; Scraper-Public vehicle research"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
        parser = VehicleCardParser()
        parser.feed(html)
        if not parser.cards:
            break
        for card in parser.cards:
            key = card.get("url") or card.get("text", "")[:160]
            if key not in seen:
                seen.add(key)
                cards.append(card)
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
