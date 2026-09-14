from __future__ import annotations

import re
from typing import Any

PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*)")
MILES_RE = re.compile(r"\b([0-9][0-9,]*)\s+mi\.?\b", re.I)
VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
YEAR_TITLE_RE = re.compile(r"\b(20\d{2})\s+([A-Za-z0-9.-]+)\s+([^\n]+)")
DIST_RE = re.compile(r"\b([A-Za-z .'-]+),\s*TX\s*\((\d+)\s*mi\)", re.I)


def _int_value(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _line_after(lines: list[str], needle: str) -> str | None:
    needle = needle.lower()
    for idx, line in enumerate(lines[:-1]):
        if line.lower() == needle:
            return lines[idx + 1] or None
    return None


def parse_cars_com_card(card: dict[str, Any]) -> dict[str, Any] | None:
    text = str(card.get("text") or "").replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title_line = next((line for line in lines if re.search(r"\b20\d{2}\s+Toyota\s+RAV4\b", line, re.I)), None)
    if not title_line:
        return None
    title = re.sub(r"^(Used|Certified|New)\s+", "", title_line, flags=re.I)
    title_match = YEAR_TITLE_RE.search(title)
    if not title_match:
        return None
    year = int(title_match.group(1))
    make = title_match.group(2)
    remainder = title_match.group(3).strip()
    if not remainder.lower().startswith("rav4"):
        return None

    price_match = PRICE_RE.search(text)
    miles_match = MILES_RE.search(text)
    price = _int_value(price_match.group(1) if price_match else None)
    mileage = _int_value(miles_match.group(1) if miles_match else None)
    if price is None or mileage is None:
        return None

    distance_match = DIST_RE.search(text)
    distance_miles = int(distance_match.group(2)) if distance_match else None
    location = distance_match.group(1).strip() + ", TX" if distance_match else None
    if distance_miles is None and re.search(r"\bSan Antonio,\s*TX\b", text, re.I):
        location, distance_miles = "San Antonio, TX", 0

    vin_match = VIN_RE.search(text)
    vin = _line_after(lines, "VIN") or (vin_match.group(1) if vin_match else None)
    dealer = _line_after(lines, "Dealer")

    return {
        "source": "cars.com",
        "source_url": card.get("url"),
        "image_url": card.get("image_url"),
        "title": title,
        "year": year,
        "make": make,
        "model": "RAV4",
        "trim": remainder[4:].strip() or None,
        "price": price,
        "mileage": mileage,
        "vin": vin,
        "stock_number": _line_after(lines, "Stock #"),
        "dealer": dealer,
        "location": location,
        "distance_miles": distance_miles,
        "drivetrain": _line_after(lines, "Drivetrain"),
        "fuel_type": _line_after(lines, "Fuel type"),
        "transmission": _line_after(lines, "Transmission"),
        "certified": bool(re.search(r"\bCertified\b", title_line, re.I)),
    }
