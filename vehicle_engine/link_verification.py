"""Conservative verification of a live vehicle detail page.

Discovery/search results are evidence of a possible listing, not proof that a
vehicle-specific URL resolves. Only a fetched page containing the expected VIN
can be elevated to a verified vehicle detail link.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit


VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
UNAVAILABLE_MARKERS = (
    "we didn't find an exact match",
    "we did not find an exact match",
    "vehicle no longer available",
    "this vehicle is no longer available",
    "this vehicle has been sold",
    "this vehicle is sold",
    "listing not found",
    "vehicle not found",
    "page not found",
    "404 not found",
)


def verify_vehicle_detail(
    *,
    status: int | None,
    requested_url: str,
    final_url: str,
    title: str,
    body: str,
    vin: str | None,
) -> tuple[bool, str]:
    """Return (verified, reason). Never rely on HTTP 200 or VIN in URL alone."""
    if status is None or not 200 <= status < 400:
        return False, "detail_http_unavailable"
    requested = urlsplit(str(requested_url))
    final = urlsplit(str(final_url))
    if requested.scheme not in ("http", "https") or not requested.hostname:
        return False, "invalid_requested_url"
    if final.scheme not in ("http", "https") or not final.hostname:
        return False, "invalid_final_url"
    expected = str(vin or "").strip().upper()
    if not VIN_RE.fullmatch(expected):
        return False, "vin_missing_or_invalid"
    page_text = f"{title}\n{body}"
    lowered = page_text.lower()
    if any(marker in lowered for marker in UNAVAILABLE_MARKERS):
        return False, "listing_unavailable_message"
    if not re.search(r"\b(?:20\d{2})\s+Toyota\s+RAV4\b", page_text, re.I):
        return False, "vehicle_identity_missing"
    if expected not in re.sub(r"\s+", "", page_text.upper()):
        return False, "vin_not_on_detail_page"
    return True, "vin_confirmed_on_detail_page"
