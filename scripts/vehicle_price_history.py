"""Public, VIN-keyed observed asking-price history for Vehicle Market & Ownership.

History is collected only from genuine generated dealer scans. No interpolated
points, no modeled market history, and no retroactive invented price changes.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HISTORY_URL = "https://xotichaze.github.io/Scraper-Public/vehicle_price_history.json"
SEED_PATH = Path("data/vehicle_price_history_seed.json")
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
MAX_OBSERVATIONS_PER_VIN = 500
PUBLIC_FIELDS = (
    "vin", "observed_at", "price", "mileage", "year", "trim", "dealer",
    "source", "source_url", "location", "area_priority", "drivetrain",
    "drivetrain_provenance", "snapshot_ref"
)


def valid_observation(row: dict) -> bool:
    try:
        date = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
        return (
            date.tzinfo is not None
            and bool(VIN_RE.fullmatch(str(row["vin"]).upper()))
            and 5000 <= int(row["price"]) <= 100000
            and 0 < int(row["mileage"]) < 300000
            and 2018 <= int(row["year"]) <= 2026
        )
    except (KeyError, TypeError, ValueError):
        return False


def observations_from_catalog(catalog: dict, snapshot_ref: str = "published_catalog") -> list[dict]:
    generated = catalog.get("generated_utc")
    if not generated:
        return []
    rows = catalog.get("market_observations") or catalog.get("vehicles") or []
    observations = []
    for vehicle in rows:
        obs = {field: vehicle.get(field) for field in PUBLIC_FIELDS if field in vehicle}
        obs["observed_at"] = generated
        obs["snapshot_ref"] = snapshot_ref
        if valid_observation(obs) and str(vehicle.get("listing_link_status")) == "verified":
            observations.append(obs)
    return observations


def merge_history(*sources: list[dict]) -> list[dict]:
    """Deduplicate by VIN+scan instant, retaining a bounded chronological series."""
    merged = {}
    for source in sources:
        for item in source:
            if not isinstance(item, dict) or not valid_observation(item):
                continue
            key = (str(item["vin"]).upper(), str(item["observed_at"]))
            item = {field: item.get(field) for field in PUBLIC_FIELDS if field in item}
            item["vin"] = key[0]
            # Keep the first known full observation for each immutable scan.
            if key not in merged:
                merged[key] = item
    by_vin = {}
    for item in merged.values():
        by_vin.setdefault(item["vin"], []).append(item)
    result = []
    for vin in sorted(by_vin):
        series = sorted(by_vin[vin], key=lambda x: x["observed_at"])
        result.extend(series[-MAX_OBSERVATIONS_PER_VIN:])
    return sorted(result, key=lambda x: (x["observed_at"], x["vin"]))


def load_seed() -> list[dict]:
    try:
        return json.loads(SEED_PATH.read_text(encoding="utf-8")).get("observations", [])
    except (OSError, ValueError):
        return []


def load_published_history() -> tuple[list[dict], bool]:
    try:
        request = urllib.request.Request(HISTORY_URL, headers={"User-Agent": "Scraper-Public-Vehicle-History/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(5_000_000).decode("utf-8"))
        if payload.get("schema") != "vehicle-price-history-v1" or not isinstance(payload.get("observations"), list):
            return [], False
        return payload["observations"], True
    except (OSError, TimeoutError, ValueError, KeyError):
        return [], False


def build_history(catalog: dict, previous_catalog: dict | None = None, *,
                  published: list[dict] | None = None,
                  published_available: bool = False,
                  bootstrap_seed: list[dict] | None = None) -> dict:
    seed = load_seed() if bootstrap_seed is None else bootstrap_seed
    previous = observations_from_catalog(previous_catalog or {}, "prior_pages_catalog")
    current = observations_from_catalog(catalog, "current_public_scan")
    values = merge_history(published or [], seed, previous, current)
    vin_count = len({v["vin"] for v in values})
    # This is a continuity warning, NOT a reason to make up history.
    source_status = "PUBLISHED_HISTORY_READ" if published_available else "SEED_AND_LAST_CATALOG_ONLY"
    return {
        "schema": "vehicle-price-history-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "continuity_status": source_status,
        "record_count": len(values),
        "vin_count": vin_count,
        "first_observed_utc": values[0]["observed_at"] if values else None,
        "latest_observed_utc": values[-1]["observed_at"] if values else None,
        "warning": "Historical asking prices are observations, not dealer quotes or sold prices. Sparse samples cannot establish a representative market trend.",
        "observations": values,
    }


def build_and_write(current_catalog_path: Path, output_path: Path, previous_path: Path | None = None) -> dict:
    current = json.loads(current_catalog_path.read_text(encoding="utf-8"))
    previous = None
    if previous_path and previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    published, available = load_published_history()
    doc = build_history(current, previous, published=published, published_available=available)
    output_path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(
        f"VEHICLE_HISTORY observations={doc['record_count']} vins={doc['vin_count']} "
        f"continuity={doc['continuity_status']}"
    )
    return doc
