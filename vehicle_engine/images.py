"""Select an actual VDP gallery photo, never a generic dealer/brand image.

Selection is conservative: reject logos, placeholders, narrow banners, icons and
unrelated page graphics. A missing credible photo is an explicit missing photo,
not an excuse to substitute a stock vehicle shot.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

BAD_IMAGE_TOKENS = (
    "logo", "favicon", "sprite", "placeholder", "no-photo", "no_image",
    "no-image", "default-image", "coming-soon", "banner", "dealericon",
    "brandmark", "googlemap", "mapbox", "facebook", "instagram", "youtube",
    "transparent", "spacer", "loading", "pixel.gif", "thumbs_up",
)
CAR_CUES = re.compile(r"\brav\s*4\b|\btoyota\b.{0,25}\brav4\b", re.I)
VIN_CUE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def valid_photo_url(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    needle = (parsed.path + "?" + parsed.query).lower()
    return not any(token in needle for token in BAD_IMAGE_TOKENS) and not re.search(r"\.svg(?:$|\?)", needle)


def select_gallery_photo(candidates: list[dict], *, vin: str | None = None) -> dict | None:
    scored: list[tuple[int, dict]] = []
    for photo in candidates:
        url = str(photo.get("url") or "").strip()
        if not valid_photo_url(url):
            continue
        width = int(photo.get("width") or 0)
        height = int(photo.get("height") or 0)
        if width < 450 or height < 225 or width / max(height, 1) > 3.0:
            continue
        alt = str(photo.get("alt") or "")
        if any(term in alt.lower() for term in (
            "photos unavailable", "photo unavailable", "no vehicle photos",
            "no photos", "no photo", "check back soon", "coming soon",
            "stock photo", "stock image", "not actual vehicle",
        )):
            continue
        gallery = bool(photo.get("gallery"))
        vehicle_text = bool(CAR_CUES.search(alt)) or bool(vin and vin.lower() in (alt + url).lower())
        if not gallery and not vehicle_text:
            continue
        score = (100 if gallery else 0) + (30 if vehicle_text else 0) + min(width // 200, 10)
        scored.append((score, {"url": url, "source": "dealer_detail_gallery" if gallery else "dealer_detail_vehicle_photo"}))
    return max(scored, key=lambda entry: entry[0])[1] if scored else None
