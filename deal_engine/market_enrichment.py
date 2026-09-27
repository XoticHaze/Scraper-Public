from __future__ import annotations

import html as html_lib
import json
import re
from statistics import median
from typing import Any
from urllib.parse import urlparse

ASIN_RE = re.compile(r"^B[0-9A-Z]{9}$", re.I)
GTIN_RE = re.compile(r"^\d{8,14}$")
CHALLENGE_MARKERS = (
    "captcha",
    "robot check",
    "access denied",
    "verify you are human",
    "sorry, we just need to make sure",
)


def identity_kind(value: Any) -> str | None:
    token = str(value or "").strip()
    if ASIN_RE.fullmatch(token):
        return "asin"
    if GTIN_RE.fullmatch(token):
        return "gtin"
    return "model" if token else None


def normalize_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def source_domain(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def html_is_challenge(html: str) -> bool:
    head = str(html or "")[:12000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


def _jsonld_blocks(html: str) -> list[Any]:
    blocks: list[Any] = []
    pattern = re.compile(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.I | re.S,
    )
    for raw in pattern.findall(html or ""):
        try:
            blocks.append(json.loads(html_lib.unescape(raw).strip()))
        except Exception:
            continue
    return blocks


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _types(row: dict[str, Any]) -> set[str]:
    raw = row.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(value or "").lower() for value in values if value}


def _identity_values(product: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in (
        "sku",
        "mpn",
        "productID",
        "productId",
        "gtin",
        "gtin8",
        "gtin12",
        "gtin13",
        "gtin14",
        "isbn",
        "asin",
        "url",
    ):
        value = product.get(key)
        if isinstance(value, (str, int, float)):
            normalized = normalize_identity(value)
            if normalized:
                values.add(normalized)
    return values


def structured_identity_match(product: dict[str, Any], identity: str) -> bool:
    target = normalize_identity(identity)
    if not target:
        return False
    return any(target == value or target in value for value in _identity_values(product))


def _condition_from_url(value: Any) -> str:
    text = str(value or "").lower()
    if "used" in text:
        return "used"
    if "refurb" in text:
        return "refurbished"
    if "openbox" in text or "open_box" in text:
        return "open_box"
    return "new"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    if not 0 < number < 100000:
        return None
    return number


def _offer_rows(offers: Any):
    if isinstance(offers, list):
        for offer in offers:
            yield from _offer_rows(offer)
        return
    if not isinstance(offers, dict):
        return
    if "offers" in offers:
        yield from _offer_rows(offers.get("offers"))
    yield offers


def extract_structured_prices(
    html: str,
    *,
    identity: str,
    identity_in_url: bool = False,
) -> list[dict[str, Any]]:
    """Extract Product/Offer prices while preserving an exact identity gate."""
    if html_is_challenge(html):
        return []

    rows: list[dict[str, Any]] = []
    for block in _jsonld_blocks(html):
        for product in _walk_json(block):
            if "product" not in _types(product):
                continue
            if not identity_in_url and not structured_identity_match(product, identity):
                continue
            for offer in _offer_rows(product.get("offers")):
                raw_price = offer.get("price") or offer.get("lowPrice") or offer.get("highPrice")
                price_spec = offer.get("priceSpecification")
                if raw_price is None and isinstance(price_spec, dict):
                    raw_price = price_spec.get("price")
                price = _number(raw_price)
                if price is None:
                    continue
                currency = str(
                    offer.get("priceCurrency")
                    or (
                        offer.get("priceSpecification", {}).get("priceCurrency")
                        if isinstance(offer.get("priceSpecification"), dict)
                        else ""
                    )
                    or "USD"
                ).upper()
                if currency != "USD":
                    continue
                rows.append(
                    {
                        "price": round(price, 2),
                        "condition": _condition_from_url(offer.get("itemCondition")),
                        "name": product.get("name"),
                    }
                )
    return rows


def extract_meta_price(html: str) -> float | None:
    if html_is_challenge(html):
        return None
    patterns = [
        r'<meta[^>]+(?:property|itemprop)=[\"\'](?:product:price:amount|price)[\"\'][^>]+content=[\"\']([0-9,]+(?:\.[0-9]+)?)[\"\']',
        r'<meta[^>]+content=[\"\']([0-9,]+(?:\.[0-9]+)?)[\"\'][^>]+(?:property|itemprop)=[\"\'](?:product:price:amount|price)[\"\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I)
        if match:
            price = _number(match.group(1))
            if price is not None:
                return round(price, 2)
    return None


def extract_labeled_price(html: str, labels: list[str]) -> float | None:
    if html_is_challenge(html):
        return None
    text = re.sub(r"<[^>]+>", " ", html_lib.unescape(html or ""))
    text = re.sub(r"\s+", " ", text)
    for label in labels:
        pattern = rf"{re.escape(label)}.{{0,100}}?\$\s*([0-9,]+(?:\.[0-9]+)?)"
        match = re.search(pattern, text, re.I)
        if match:
            price = _number(match.group(1))
            if price is not None:
                return round(price, 2)
    return None


def select_observation_price(
    html: str,
    *,
    identity: str,
    identity_in_url: bool,
    price_labels: list[str] | None = None,
) -> tuple[float | None, str]:
    structured = extract_structured_prices(
        html,
        identity=identity,
        identity_in_url=identity_in_url,
    )
    if structured:
        return float(median(row["price"] for row in structured)), "jsonld"
    if identity_in_url:
        meta = extract_meta_price(html)
        if meta is not None:
            return meta, "meta"
        labeled = extract_labeled_price(html, price_labels or [])
        if labeled is not None:
            return labeled, "labeled"
    return None, "none"


def merge_current_observation(
    record: dict[str, Any],
    observation: dict[str, Any],
    *,
    history_limit: int = 90,
) -> None:
    """Keep one current observation per source URL and bounded observation history."""
    url = str(observation.get("url") or "")
    current = [
        row
        for row in (record.get("observations") or [])
        if str(row.get("url") or "") != url
    ]
    current.append(observation)
    record["observations"] = current

    history = list(record.get("observation_history") or [])
    history.append(observation)
    dedup: dict[tuple[str, str, float], dict[str, Any]] = {}
    for row in history:
        price = _number(row.get("price"))
        if price is None:
            continue
        key = (
            str(row.get("url") or ""),
            str(row.get("observed_at") or ""),
            round(price, 2),
        )
        dedup[key] = row
    record["observation_history"] = list(dedup.values())[-history_limit:]


def reject_price_outliers(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usable = [row for row in observations if _number(row.get("price")) is not None]
    if len(usable) < 3:
        return usable
    center = float(median(_number(row.get("price")) for row in usable))
    if center <= 0:
        return usable
    return [
        row
        for row in usable
        if 0.4 * center <= float(_number(row.get("price"))) <= 2.5 * center
    ]


def update_confidence(record: dict[str, Any]) -> None:
    filtered = reject_price_outliers(list(record.get("observations") or []))
    record["observations"] = filtered
    domains = {
        source_domain(str(row.get("url") or ""))
        for row in filtered
        if source_domain(str(row.get("url") or ""))
    }
    if len(domains) >= 2:
        confidence = "high"
    elif len(domains) == 1:
        confidence = "medium"
    else:
        confidence = "unknown"
    record["price_confidence"] = confidence
    if filtered:
        record["observed_at"] = max(str(row.get("observed_at") or "") for row in filtered)
        record["status"] = "verified_external"


def merged_market_records(
    canonical: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge prior runtime observations under canonical policy/overrides."""
    previous = previous or {}
    result = {
        "schema": canonical.get("schema") or "macbid-market-values-v1",
        "version": max(int(canonical.get("version") or 1), int(previous.get("version") or 1)),
        "updated_at": canonical.get("updated_at") or previous.get("updated_at"),
        "defaults": {**(previous.get("defaults") or {}), **(canonical.get("defaults") or {})},
        "valuations": [],
    }
    prev_map = {
        str(row.get("identity")): row
        for row in (previous.get("valuations") or [])
        if isinstance(row, dict) and row.get("identity")
    }
    canon_map = {
        str(row.get("identity")): row
        for row in (canonical.get("valuations") or [])
        if isinstance(row, dict) and row.get("identity")
    }
    for identity in sorted(set(prev_map) | set(canon_map)):
        prior = dict(prev_map.get(identity) or {})
        manual = dict(canon_map.get(identity) or {})
        merged = {**prior, **{k: v for k, v in manual.items() if k != "observations"}}
        observations: dict[str, dict[str, Any]] = {}
        for row in list(prior.get("observations") or []) + list(manual.get("observations") or []):
            url = str(row.get("url") or "")
            if url:
                observations[url] = row
        merged["observations"] = list(observations.values())
        history = list(prior.get("observation_history") or [])
        if history:
            merged["observation_history"] = history[-90:]
        update_confidence(merged)
        result["valuations"].append(merged)
    return result
