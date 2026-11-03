"""Conservative, manufacturer-sticker-supported RAV4 VIN-family drive clues.

A build-family pattern is *not* an exact-VIN factory sticker or an independent
inspection. Only 2025 patterns with reviewed Toyota window-sticker examples
are admitted. Unknown models/years/VINs stay unknown.
"""
from __future__ import annotations

import re

_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# Reference Toyota factory window stickers for other vehicles of the same
# 2025 WMI/VDS/year family; never represent them as the target car's sticker.
_2025_FAMILY_EVIDENCE = {
    "2T3F1RFV": (
        "All-wheel Drive",
        "https://www.whiterivertoyota.com/resrc/toyotawindowsticker/getByVIN/?vin=2T3F1RFV5SW608805",
    ),
    "2T3W1RFV": (
        "Front-wheel Drive",
        "https://static.foxdealer.com/window_stickers/d/5/a/0ccd22f734401c8222a158fcc013cbe6d75ead5a.pdf",
    ),
}


def infer_2025_rav4_drivetrain(
    vin: str | None, year: int | None, make: str | None, model: str | None
) -> dict[str, str] | None:
    """Return an explicitly unconfirmed family inference, never dealer proof."""
    try:
        if int(year) != 2025:
            return None
    except (TypeError, ValueError):
        return None
    if str(make or "").strip().lower() != "toyota":
        return None
    if str(model or "").strip().lower() != "rav4":
        return None
    normalized = str(vin or "").strip().upper()
    if not _VIN.fullmatch(normalized) or normalized[9] != "S":
        return None
    build = _2025_FAMILY_EVIDENCE.get(normalized[:8])
    if build is None:
        return None
    drivetrain, example_sticker = build
    return {
        "drivetrain": drivetrain,
        "drivetrain_provenance": "vin_family_inferred",
        "drivetrain_evidence_url": example_sticker,
    }
