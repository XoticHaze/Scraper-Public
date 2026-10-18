"""Source-neutral normalization for auctioneer-owned fixed-price storefront lots.

Not HiBid auction data. A store's compare-at price is a seller claim, never a
verified market valuation or an automated purchase/auction-bid ceiling.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse


FOCUS_TERMS = {
    "power": ("ups", "uninterruptible", "cyberpower", "eaton", "apc ", "battery backup"),
    "music": ("roland", "nord ", "korg", "arturia", "akai", "synth", "midi", "digital piano", "electronic keyboard", "keyboard piano", "61-key", "49-key", "73-key", "88-key"),
    "solar": ("solar", "mppt", "inverter", "charge controller"),
    "homelab": ("server rack", "network rack", "rackmount", "nas ", "router", "poe ", "minipc", "mini pc"),
    "home": ("dishwasher", "kitchen sink", "storage rack", "storage shelf", "shelving", "vanity"),
}
CONDITION_MARKERS = (
    ("exclude", ("damaged", "broken", "not working", "parts only", "as is", "for parts")),
    ("used", ("used", "refurbished", "pre-owned")),
    ("open_box", ("open box", "open-box")),
    ("new", ("brand new", "(new)", " sealed", " new ")),
)


def as_price(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return round(number, 2) if 0 < number < 100_000 else None


def classify(title: str) -> tuple[str, list[str]]:
    lower = f" {title.lower()} "
    condition = next((status for status, tokens in CONDITION_MARKERS if any(t in lower for t in tokens)), "unknown")
    focus = [group for group, tokens in FOCUS_TERMS.items() if any(t in lower for t in tokens)]
    return condition, focus


def normalize_product(product: dict[str, Any], *, tax_rate: float = 0.0825) -> dict[str, Any] | None:
    if not isinstance(product, dict) or not product.get("id"):
        return None
    title = re.sub(r"\s+", " ", str(product.get("title") or "")).strip()
    handle = str(product.get("handle") or "").strip()
    if not title or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,220}", handle):
        return None
    variants = product.get("variants") or []
    available = [
        variant for variant in variants
        if isinstance(variant, dict) and variant.get("available") is True
        and as_price(variant.get("price")) is not None
    ]
    if not available:
        return None
    cheapest = min(available, key=lambda item: as_price(item["price"]))
    price = as_price(cheapest["price"])
    stated = as_price(cheapest.get("compare_at_price"))
    condition, focus = classify(title)
    if condition == "exclude":
        return None
    image = next((str(img.get("src")) for img in (product.get("images") or [])
                  if isinstance(img, dict) and str(img.get("src") or "").startswith("https://")), None)
    spread = round((stated - price) / stated * 100, 1) if stated and stated > price else None
    return {
        "source": "paotexas_storefront",
        "source_type": "buy_it_now",
        "identity": "paotexas:" + str(product["id"]),
        "title": title[:250],
        "url": "https://paotexas.com/products/" + quote(handle),
        "price": price,
        "estimated_sales_tax": round(price * tax_rate, 2),
        "estimated_all_in": round(price * (1 + tax_rate), 2),
        "shipping": "not_included; verify in checkout",
        "fee_model": "fixed_price_no_auction_premium",
        "seller_stated_compare_at": stated,
        "seller_stated_discount_pct": spread,
        "market_verified": False,
        "condition": condition,
        "focus": focus,
        "vendor": str(product.get("vendor") or "")[:120],
        "category": str(product.get("product_type") or "")[:120],
        "image_url": image,
        "score": round(len(focus) * 50 + (spread or 0) * .15 + (5 if condition == "new" else 0), 2),
    }


def build_catalog(products: list[dict[str, Any]], *, observed_at: str, tax_rate: float = 0.0825) -> dict[str, Any]:
    unique = {}
    for raw in products:
        row = normalize_product(raw, tax_rate=tax_rate)
        if row:
            unique[row["identity"]] = row
    rows = sorted(unique.values(), key=lambda row: (-row["score"], row["estimated_all_in"], row["title"]))
    return {
        "schema": "scraper-storefront-catalog-v1",
        "source": "paotexas_storefront",
        "source_type": "buy_it_now_not_hibid_auction",
        "observed_at": observed_at,
        "tax_rate_estimate": tax_rate,
        "market_value_authority": "none; compare-at prices are unverified seller claims",
        "product_count": len(rows),
        "focused_count": sum(bool(r["focus"]) for r in rows),
        "products": rows,
    }
