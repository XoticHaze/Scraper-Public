"""GSA Auctions official public JSON API collector and conservative auction normalizer.

Only GSA's documented public API is used. No bid/purchase/account endpoint.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

GSA_ENDPOINT = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"
MAX_BYTES = 24_000_000
OFFICIAL_HOSTS = {"www.gsaauctions.gov", "gsaauctions.gov", "www.gsa.gov", "gsa.gov"}
SOURCE_SCHEMA = "scraper-gsa-auctions-v1"


class GSASourceError(ValueError):
    pass


def _field(row, name):
    if name in row:
        return row[name]
    for k, value in row.items():
        if str(k).lower() == name.lower():
            return value
    return None


def _text(value):
    return str(value or "").strip()


def _number(value):
    try:
        if value is None or isinstance(value, bool) or str(value).strip() == "":
            return None
        amount = float(str(value).replace(",", ""))
        return round(amount, 2) if 0 <= amount < 1_000_000_000 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _date_only(value):
    raw = _text(value)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _official_url(value):
    p = urlsplit(_text(value))
    if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in OFFICIAL_HOSTS:
        return None
    if p.username or p.password:
        return None
    # Discard query parameters and fragments, preventing tracking and credentials being published.
    return urlunsplit(("https", p.hostname.lower(), p.path or "/", "", ""))


def _records(obj, depth=0):
    """Find the documented auction rows; reject unknown responses instead of inventing rows."""
    if depth > 4:
        raise GSASourceError("GSA response nesting exceeds validation bound")
    if isinstance(obj, list):
        if not obj:
            return []
        if all(isinstance(x, dict) and _field(x, "SaleNo") is not None for x in obj):
            return obj
        for entry in obj[:10]:
            if isinstance(entry, (list, dict)):
                try:
                    rows = _records(entry, depth + 1)
                    if rows:
                        return rows
                except GSASourceError:
                    pass
        raise GSASourceError("GSA response array does not contain auction records")
    if isinstance(obj, dict):
        if _field(obj, "SaleNo") is not None:
            return [obj]
        for k in ("auctions", "Auctions", "data", "results", "items", "records", "List"):
            if k in obj:
                return _records(obj[k], depth + 1)
        raise GSASourceError("GSA JSON response lacks documented auction field structure")
    raise GSASourceError("GSA JSON response is not an object or list")


def normalize_gsa_auctions(payload, *, observed_at=None, state=None, active_only=True):
    """Preserve date-only close evidence; no fabricated countdown, all-in price, or bid advice."""
    values = _records(payload)
    if observed_at is None:
        stamp = datetime.now(timezone.utc).isoformat()
    elif isinstance(observed_at, datetime) and observed_at.tzinfo is not None:
        stamp = observed_at.astimezone(timezone.utc).isoformat()
    else:
        raise ValueError("observed_at must be timezone-aware")

    output, seen = [], set()
    for row in values:
        sale = _text(_field(row, "SaleNo"))
        lot = _text(_field(row, "LotNo"))
        title = _text(_field(row, "ItemName") or _field(row, "LotDescript"))
        status = _text(_field(row, "AuctionStatus")).upper()
        if not sale or not lot or not title or not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", sale):
            continue
        if status != "A" and active_only:
            continue
        item_state = _text(_field(row, "PropertyState")).upper()
        if state is not None and item_state != state.upper():
            continue
        key = f"{sale}:{lot}"
        if key in seen:
            continue
        seen.add(key)
        url = _official_url(_field(row, "ItemDescURL"))
        image = _official_url(_field(row, "ImageURL"))
        output.append({
            "source": "gsa", "offer_id": "gsa:" + key,
            "sale_number": sale, "lot_number": lot,
            "title": title, "condition": "as_is",
            "auction_status": "active" if status == "A" else "not_verified_active",
            "current_bid": _number(_field(row, "HighBidAmount")),
            "reserve": _number(_field(row, "Reserve")),
            "bidder_count": _number(_field(row, "BiddersCount")),
            "min_bid_increment": _number(_field(row, "AucIncrement")),
            "closing_date": _date_only(_field(row, "AucEndDt")),
            "closing_time": None,
            "time_precision": "date_only",
            "city": _text(_field(row, "PropertyCity")),
            "state": item_state,
            "zipcode": _text(_field(row, "PropertyZip")),
            "agency": _text(_field(row, "AgencyName")),
            "url": url,
            "image_url": image,
            "observed_at": stamp,
            "verified_all_in_total": None,
            "max_bid": None,
            "seller_authenticity": "official_federal_api",
            "provenance": "api.gsa.gov/assets/gsaauctions/v2/auctions",
        })
    return output


def fetch_gsa_auctions(*, key=None, timeout=18):
    """Official API demo key is permitted for one-off evaluation only; don't schedule it."""
    api_key = key or os.environ.get("GSA_API_KEY")
    if not api_key:
        raise GSASourceError("GSA_API_KEY not configured (demo key is probe-only)")
    url = GSA_ENDPOINT + "?" + urlencode({"api_key": api_key, "format": "JSON"})
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "Scraper-Public GSA research/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise GSASourceError("GSA response exceeds size limit")
            if "json" not in str(response.headers.get("Content-Type") or "").lower() and not body.lstrip().startswith((b"{", b"[")):
                raise GSASourceError("GSA did not return JSON")
        return json.loads(body)
    except GSASourceError:
        raise
    except Exception:
        # Never include API key or a signed redirect URL in a diagnostic.
        raise GSASourceError("GSA network, HTTP, or JSON response failed") from None


def build_gsa_catalog(payload, *, state=None, observed_at=None):
    stamp = observed_at if observed_at is not None else datetime.now(timezone.utc)
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("catalog observation time must be timezone-aware")
    rows = normalize_gsa_auctions(payload, observed_at=stamp, state=state)
    return {
        "schema": SOURCE_SCHEMA, "source": "gsa",
        "source_status": "verified_live_api_response",
        "observed_at": stamp.astimezone(timezone.utc).isoformat(),
        "filter_state": state,
        "count": len(rows),
        "source_time_precision": "date_only",
        "auctions": rows,
        "warning": "Current bids are not landed costs. As-is items; verify reserve, auction end time, pickup, fees and shipping with GSA.",
    }
