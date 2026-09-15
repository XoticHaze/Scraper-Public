from __future__ import annotations

import re
from typing import Any

PRICE_RE = re.compile(r"\$\s*([0-9][0-9,]*)")
PLAIN_PRICE_RE = re.compile(r"^\$?([0-9]{1,3}(?:,[0-9]{3})+)$")
MILES_RE = re.compile(r"\b([0-9][0-9,]*)\s+(?:mi\.?|miles?)\b", re.I)
MILES_K_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)K\s*mi\b", re.I)
VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
YEAR_TITLE_RE = re.compile(r"\b(20\d{2})\s+([A-Za-z0-9.-]+)\s+([^\n]+)")
DIST_RE = re.compile(r"\b([A-Za-z .'-]+),\s*TX\s*\((\d+)\s*mi\)", re.I)
AWAY_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*mi\.?\s*away\b", re.I)


def _int_value(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _mileage_from_text(text: str) -> int | None:
    match = MILES_RE.search(text)
    if match:
        return _int_value(match.group(1))
    match = MILES_K_RE.search(text)
    if match:
        return int(round(float(match.group(1)) * 1000))
    return None


def _line_after(lines: list[str], needle: str) -> str | None:
    needle = needle.lower()
    for idx, line in enumerate(lines[:-1]):
        if line.lower() == needle:
            return lines[idx + 1] or None
    return None


def _label_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    lowered = tuple(label.lower() for label in labels)
    for idx, line in enumerate(lines):
        low = line.lower().rstrip(":")
        if low in lowered:
            if idx + 1 < len(lines):
                return lines[idx + 1]
        for label in lowered:
            prefix = label + ":"
            if line.lower().startswith(prefix):
                value = line[len(prefix):].strip()
                if value:
                    return value
    return None


def _dealer_price(lines: list[str], text: str) -> int | None:
    """Prefer an advertised/final dealer price over MSRP/retail values."""
    preferred_labels = (
        "cavender price", "shottenkirk price", "asking price", "internet price",
        "sale price", "our price", "price",
    )
    for label in preferred_labels:
        pattern = re.compile(rf"\b{re.escape(label)}\b[^$\n]*\$\s*([0-9][0-9,]*)", re.I)
        match = pattern.search(text)
        if match:
            return _int_value(match.group(1))
        value = _label_value(lines, (label,))
        if value:
            match = PRICE_RE.search(value)
            if match:
                return _int_value(match.group(1))

    for idx, line in enumerate(lines):
        match = PRICE_RE.search(line)
        if not match:
            continue
        context = " ".join(lines[max(0, idx - 1): idx + 1]).lower()
        if any(token in context for token in ("msrp", "retail", "market value", "per month", "/mo")):
            continue
        value = _int_value(match.group(1))
        if value and value >= 5000:
            return value
    return None


def parse_dealer_detail(page: dict[str, Any], dealer: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a rendered local-dealer vehicle detail page."""
    text = str(page.get("text") or "").replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not re.search(r"\b20\d{2}\s+Toyota\s+RAV4\b", text, re.I):
        return None

    title_line = next(
        (
            line for line in lines
            if re.search(r"\b20\d{2}\s+Toyota\s+RAV4\b", line, re.I)
            and len(line) <= 140
        ),
        None,
    )
    if not title_line:
        title_match = re.search(r"\b(20\d{2}\s+Toyota\s+RAV4[^\n]{0,80})", text, re.I)
        title_line = title_match.group(1).strip() if title_match else None
    if not title_line:
        return None

    title = re.sub(
        r"^(?:Certified Pre-Owned|Certified|Gold Certified|Silver Certified|Pre-Owned|Used)\s+",
        "",
        title_line,
        flags=re.I,
    )
    match = YEAR_TITLE_RE.search(title)
    if not match:
        return None
    year = int(match.group(1))
    make = match.group(2)
    remainder = match.group(3).strip()
    if not remainder.lower().startswith("rav4"):
        return None

    price = _dealer_price(lines, text)
    mileage_value = _label_value(lines, ("odometer", "mileage"))
    mileage = _mileage_from_text(mileage_value or "") or _mileage_from_text(text)
    if price is None or mileage is None:
        return None

    vin = _label_value(lines, ("vin",))
    if vin:
        vin_match = VIN_RE.search(vin)
        vin = vin_match.group(1) if vin_match else None
    if not vin:
        vin_match = VIN_RE.search(text)
        vin = vin_match.group(1) if vin_match else None

    drivetrain = _label_value(lines, ("drivetrain", "drive type"))
    if not drivetrain:
        if re.search(r"\b(?:4WD/AWD|All-Wheel Drive|AWD)\b", text, re.I):
            drivetrain = "All-wheel Drive"
        elif re.search(r"\bFront-Wheel Drive\b", text, re.I):
            drivetrain = "Front-Wheel Drive"

    return {
        "source": str(dealer.get("id") or "local_dealer"),
        "source_kind": "direct_dealer",
        "source_url": page.get("url"),
        "image_url": page.get("image_url"),
        "title": title,
        "year": year,
        "make": make,
        "model": "RAV4",
        "trim": remainder[4:].strip() or None,
        "price": price,
        "mileage": mileage,
        "vin": vin,
        "stock_number": _label_value(lines, ("stock number", "stock #", "stock")),
        "dealer": dealer.get("name"),
        "location": dealer.get("location", "San Antonio, TX"),
        "distance_miles": dealer.get("distance_miles"),
        "market_local": bool(dealer.get("market_local", True)),
        "locality_hint": dealer.get("locality_hint"),
        "area_priority": dealer.get("area_priority"),
        "drivetrain": drivetrain,
        "fuel_type": _label_value(lines, ("fuel type", "fuel")),
        "transmission": _label_value(lines, ("transmission",)),
        "certified": bool(re.search(r"\bCertified\b", title_line, re.I) or re.search(r"\bGold Certified\b|\bSilver Certified\b", text, re.I)),
        "dealer_doc_fee": dealer.get("doc_fee"),
        "dealer_mandatory_addon_amount": float(dealer.get("mandatory_addon_amount") or 0),
        "dealer_addon_warning": dealer.get("addon_warning"),
    }


def parse_autotrader_card(card: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one rendered Autotrader result card without requiring its VDP."""
    text = str(card.get("text") or "").replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title_idx = next((idx for idx, line in enumerate(lines) if re.search(r"\b20\d{2}\s+Toyota\s+RAV4\b", line, re.I)), None)
    if title_idx is None:
        return None
    raw_title = re.sub(r"^(?:Used|Certified|Toyota Gold Certified|Toyota Silver Certified)\s*", "", lines[title_idx], flags=re.I)
    title_match = re.search(r"\b(20\d{2})\s+Toyota\s+RAV4(?:\s+([^\n]+))?", raw_title, re.I)
    if not title_match:
        return None
    year = int(title_match.group(1))
    trim = (title_match.group(2) or "").strip() or None
    if not trim and title_idx + 1 < len(lines):
        candidate = lines[title_idx + 1].lstrip("* ").strip()
        if candidate and not re.search(r"\b(?:mi|miles?)\b", candidate, re.I) and len(candidate) <= 60:
            trim = candidate

    mileage = _mileage_from_text(text)
    if mileage is None:
        return None

    price = None
    for line in lines[title_idx + 1:]:
        match = PLAIN_PRICE_RE.match(line.replace("$", ""))
        if not match:
            continue
        value = _int_value(match.group(1))
        if value and 5000 <= value <= 100000:
            price = value
            break
    if price is None:
        match = PRICE_RE.search(text)
        price = _int_value(match.group(1) if match else None)
    if price is None:
        return None

    distance_match = AWAY_RE.search(text)
    distance = float(distance_match.group(1)) if distance_match else None
    dealer = None
    if distance_match:
        for idx, line in enumerate(lines):
            if AWAY_RE.search(line):
                for candidate in reversed(lines[max(0, idx - 4):idx]):
                    low = candidate.lower().strip("* ")
                    if not low or any(token in low for token in (
                        "dealer fees", "great price", "good price", "no accidents", "sponsored",
                        "online paperwork", "delivery", "request info", "see payment",
                    )):
                        continue
                    dealer = candidate.strip("* ")
                    break
                break

    certified = bool(re.search(r"\bCertified\b|Toyota Gold Certified|Toyota Silver Certified", text, re.I))
    title = f"{year} Toyota RAV4{f' {trim}' if trim else ''}"
    return {
        "source": str(source.get("id") or "autotrader"),
        "source_kind": "aggregator",
        "source_url": card.get("url"),
        "image_url": card.get("image_url"),
        "title": title,
        "year": year,
        "make": "Toyota",
        "model": "RAV4",
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "vin": None,
        "stock_number": None,
        "dealer": dealer,
        "location": source.get("location", "San Antonio, TX"),
        "distance_miles": distance,
        "market_local": bool(distance is not None and distance <= 25),
        "locality_hint": None,
        "area_priority": source.get("area_priority"),
        "drivetrain": "All-wheel Drive" if re.search(r"\bAWD/4WD\b|\bAWD\b|All-Wheel", text, re.I) else None,
        "fuel_type": "Hybrid" if re.search(r"\bHybrid\b", text, re.I) else "Gasoline",
        "transmission": None,
        "certified": certified,
        "dealer_doc_fee": None,
        "dealer_mandatory_addon_amount": 0,
        "dealer_addon_warning": None,
    }


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
    miles = _mileage_from_text(text)
    price = _int_value(price_match.group(1) if price_match else None)
    mileage = miles
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
        "source_kind": "aggregator",
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
