from deal_engine.storefront import build_catalog, normalize_product


def sample(*, ident=11, title="APC UPS Battery Backup (Open Box)", price="100.00",
           compare_at="220.00", available=True, handle="apc-ups"):
    return {
        "id": ident, "title": title, "handle": handle,
        "variants": [{"available": available, "price": price, "compare_at_price": compare_at}],
        "images": [{"src": "https://cdn.shopify.com/images/example.jpg"}],
        "vendor": "APC", "product_type": "Electronics",
    }


def test_fixed_price_feed_has_no_auction_premium_or_lot_fee():
    item = normalize_product(sample())
    assert item["source_type"] == "buy_it_now"
    assert item["price"] == 100.0
    assert item["estimated_sales_tax"] == 8.25
    assert item["estimated_all_in"] == 108.25
    assert item["fee_model"] == "fixed_price_no_auction_premium"
    assert item["market_verified"] is False
    assert item["seller_stated_discount_pct"] == 54.5
    assert item["focus"] == ["power"]


def test_unavailable_and_broken_items_fail_closed():
    assert normalize_product(sample(available=False)) is None
    assert normalize_product(sample(title="APC UPS DAMAGED")) is None
    assert normalize_product(sample(price="0")) is None
    assert normalize_product(sample(handle="javascript:alert(1)")) is None


def test_unknown_compare_at_does_not_emit_savings():
    item = normalize_product(sample(compare_at=None))
    assert item["seller_stated_compare_at"] is None
    assert item["seller_stated_discount_pct"] is None


def test_catalog_is_deduped_and_preference_ranked():
    products = [
        sample(ident=12, title="Plain shirts", handle="shirts", price="5.00"),
        sample(ident=11),
        sample(ident=11),
        sample(ident=13, title="Nord Lead 4 synthesizer", handle="nord-lead-4", price="800.00"),
    ]
    report = build_catalog(products, observed_at="2026-10-18T08:00:00Z")
    assert report["source_type"] == "buy_it_now_not_hibid_auction"
    assert report["product_count"] == 3
    assert report["focused_count"] == 2
    assert "power" in report["products"][0]["focus"] or "music" in report["products"][0]["focus"]
    assert report["products"][-1]["title"] == "Plain shirts"


def test_unverified_seller_reference_never_becomes_market_authority():
    report = build_catalog([sample()], observed_at="2026-10-18T08:00:00Z")
    assert report["products"][0]["market_verified"] is False
    assert "unverified seller claims" in report["market_value_authority"]
