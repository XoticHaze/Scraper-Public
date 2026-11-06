"""Source-specific read-only item normalization. No automatic buying or authenticity claims."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

API_SCHEMA = "scraper-marketplace-offers-v1"


def _money(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        amount = float(value)
        return round(amount, 2) if 0 < amount < 1_000_000 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _ts(observed_at=None):
    if observed_at is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(observed_at, datetime):
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return observed_at.astimezone(timezone.utc).isoformat()
    raise TypeError("observed_at must be a datetime or None")


def _safe_link(value, domains):
    """Allow a known official HTTP(S) host; remove query strings that may carry keys."""
    if not isinstance(value, str):
        return None
    p = urlsplit(value)
    hostname = (p.hostname or "").lower()
    if p.scheme.lower() not in {"http", "https"} or hostname not in domains:
        return None
    if p.username or p.password:
        return None
    # For product landing links, strip tracking parameters and never expose API keys.
    return urlunsplit(("https", hostname, p.path or "/", "", p.fragment))


def _aspect(item, key):
    return [str(a.get("value") or "").strip() for a in (item.get("localizedAspects") or [])
            if isinstance(a, dict) and str(a.get("name") or "").lower() == key.lower() and a.get("value")]


def ebay_risk(item, *, expected_model_ids=()):
    """A cautious triage, not verification of a seller, manufacturer, or serial number."""
    warnings = []
    critical = []
    seller = item.get("seller") or {}
    score = seller.get("feedbackScore")
    positive = seller.get("positiveFeedbackPercent")
    try:
        if score is None or int(score) < 30:
            warnings.append("seller_history_insufficient")
    except (TypeError, ValueError):
        warnings.append("seller_history_insufficient")
    try:
        if positive is None or float(positive) < 97:
            warnings.append("seller_feedback_insufficient")
    except (TypeError, ValueError):
        warnings.append("seller_feedback_insufficient")

    terms = item.get("returnTerms") or {}
    if terms.get("returnsAccepted") is False:
        warnings.append("seller_no_returns")
    elif terms.get("returnsAccepted") is None:
        warnings.append("return_policy_unverified")
    title = str(item.get("title") or "")
    model_values = _aspect(item, "Model") + _aspect(item, "Model Number")
    if "airpods" in title.lower() and any("earpods" in v.lower() and "airpods" not in v.lower() for v in model_values):
        critical.append("contradictory_product_model")
    expected = {re.sub(r"[^A-Z0-9]", "", v.upper()) for v in expected_model_ids if v}
    if expected and model_values:
        found = {re.sub(r"[^A-Z0-9]", "", v.upper()) for v in model_values}
        if not expected.intersection(found):
            critical.append("expected_model_not_matched")
    elif expected:
        warnings.append("exact_model_not_verified")
    if not model_values:
        warnings.append("model_identity_missing")
    if not item.get("image") and not item.get("additionalImages"):
        warnings.append("images_missing")
    if not seller.get("username"):
        warnings.append("seller_identity_missing")
    if not item.get("itemWebUrl"):
        critical.append("official_listing_url_missing")
    return {
        "decision": "PASS" if critical else "REVIEW",
        "authenticity_status": "conflicting_evidence" if critical else "not_verified",
        "seller_status": "needs_evidence" if warnings else "unverified_category_feedback",
        "critical_flags": sorted(set(critical)),
        "warnings": sorted(set(warnings)),
    }


def normalize_ebay_item(item, *, observed_at=None, expected_model_ids=()):
    """Normalize the read-only eBay Browse GET item response."""
    if not isinstance(item, dict):
        raise TypeError("eBay item response must be an object")
    item_id = str(item.get("itemId") or item.get("legacyItemId") or "").strip()
    title = str(item.get("title") or "").strip()
    offer_price = item.get("price") or {}
    price = _money(offer_price.get("value") if isinstance(offer_price, dict) else None)
    currency = str(offer_price.get("currency") or "") if isinstance(offer_price, dict) else ""
    url = _safe_link(item.get("itemWebUrl"), {"www.ebay.com", "ebay.com"})
    if not item_id or not title or price is None or currency != "USD" or not url:
        raise ValueError("eBay item lacks required identity, USD price, or official URL")
    seller = item.get("seller") or {}
    image = item.get("image") or {}
    risk = ebay_risk(item, expected_model_ids=expected_model_ids)
    shipping = []
    for option in item.get("shippingOptions") or []:
        if isinstance(option, dict):
            cost = option.get("shippingCost") or {}
            amount = _money(cost.get("value")) if isinstance(cost, dict) else None
            if amount is not None or (isinstance(cost, dict) and str(cost.get("value")) in {"0", "0.0", "0.00"}):
                shipping.append(float(cost["value"]))
    return {
        "schema": API_SCHEMA, "source": "ebay", "offer_id": "ebay:" + item_id,
        "product_identity": {"gtin": item.get("gtin"), "model_values": _aspect(item, "Model")},
        "title": title, "price": price, "currency": "USD", "condition": item.get("condition"),
        "seller": {"name": seller.get("username"), "feedback_score": seller.get("feedbackScore"),
                   "positive_feedback_pct": seller.get("positiveFeedbackPercent"), "type": "third_party"},
        "url": url, "image_url": _safe_link(image.get("imageUrl"), {"i.ebayimg.com", "i1.ebayimg.com"}) if isinstance(image, dict) else None,
        "shipping_min": min(shipping) if shipping else None,
        "all_in_status": "incomplete_shipping_tax_unknown",
        "end_at": item.get("itemEndDate"), "observed_at": _ts(observed_at), "risk": risk,
        "provenance": "ebay_browse_item_api", "live_verified": False,
    }


def _bestbuy_link(links, sku):
    link = _safe_link((links or {}).get("web"), {"www.bestbuy.com", "bestbuy.com"})
    return link or "https://www.bestbuy.com/site/searchpage.jsp"


def normalize_bestbuy_products(payload, *, observed_at=None):
    """Standard Products API collection or single-SKU result, first-party retail only."""
    products = payload.get("products", []) if isinstance(payload, dict) else []
    if isinstance(payload, dict) and "sku" in payload:
        products = [payload]
    if not isinstance(products, list):
        raise ValueError("Best Buy products must be an array")
    rows = []
    stamp = _ts(observed_at)
    for item in products:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku") or "")
        price = _money(item.get("salePrice"))
        if not re.fullmatch(r"\d{5,15}", sku) or not item.get("name") or price is None:
            continue
        rows.append({
            "schema": API_SCHEMA, "source": "bestbuy", "offer_id": "bestbuy:new:" + sku,
            "product_identity": {"bestbuy_sku": sku, "upc": item.get("upc"), "model": item.get("modelNumber")},
            "title": item["name"], "price": price, "currency": "USD", "condition": "new",
            "seller": {"name": "Best Buy", "type": "retailer_direct"},
            "url": _safe_link(item.get("url"), {"www.bestbuy.com", "bestbuy.com", "api.bestbuy.com"}) or "https://www.bestbuy.com/site/searchpage.jsp",
            "image_url": item.get("image") if isinstance(item.get("image"), str) and item["image"].startswith("https://") else None,
            "availability": item.get("onlineAvailability"), "shipping_min": None,
            "all_in_status": "incomplete_shipping_tax_unknown", "observed_at": stamp,
            "risk": {"decision": "REVIEW", "authenticity_status": "first_party_catalog_not_physical_item_verified",
                     "critical_flags": [], "warnings": ["price_and_stock_recheck_at_checkout"]},
            "provenance": "bestbuy_products_api", "live_verified": False,
        })
    return rows


def normalize_bestbuy_open_box(payload, *, observed_at=None):
    """Buying Options API responses contain multiple condition offers per SKU."""
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("Best Buy open-box response missing results")
    rows = []
    stamp = _ts(observed_at)
    for product in results:
        if not isinstance(product, dict):
            continue
        sku = str(product.get("sku") or "")
        title = ((product.get("names") or {}).get("title")) if isinstance(product.get("names"), dict) else None
        if not re.fullmatch(r"\d{5,15}", sku) or not title:
            continue
        for index, offer in enumerate(product.get("offers") or []):
            if not isinstance(offer, dict):
                continue
            condition = str(offer.get("condition") or "").lower()
            prices = offer.get("prices") or {}
            amount = _money(prices.get("current")) if isinstance(prices, dict) else None
            if condition not in {"excellent", "certified"} or amount is None:
                continue
            rows.append({
                "schema": API_SCHEMA, "source": "bestbuy",
                "offer_id": f"bestbuy:openbox:{sku}:{condition}:{index}",
                "product_identity": {"bestbuy_sku": sku}, "title": title,
                "price": amount, "currency": "USD", "condition": "open_box_" + condition,
                "seller": {"name": "Best Buy", "type": "retailer_direct"},
                "url": _bestbuy_link(product.get("links"), sku),
                "image_url": None, "availability": "api_reported_available",
                "shipping_min": None, "all_in_status": "incomplete_shipping_tax_unknown",
                "observed_at": stamp,
                "risk": {"decision": "REVIEW", "authenticity_status": "first_party_catalog_not_physical_item_verified",
                         "critical_flags": [], "warnings": ["availability_is_address_dependent", "recheck_accessories_and_condition"]},
                "provenance": "bestbuy_buying_options_api", "live_verified": False,
            })
    return rows
