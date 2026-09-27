from deal_engine.valuation import (
    derive_market_valuation,
    price_stats,
    reverse_max_bid,
    summarize_market_value,
)


def test_price_stats_uses_median_average_range_and_sample_count():
    observations = [
        {"condition": "new", "price": 100},
        {"condition": "new", "price": 120},
        {"condition": "open_box", "price": 70},
    ]
    assert price_stats(observations, {"new"}) == {
        "median": 110.0,
        "average": 110.0,
        "low": 100.0,
        "high": 120.0,
        "samples": 2,
    }


def test_reverse_max_bid_backs_out_tax_fee_and_buyer_premium():
    bid = reverse_max_bid(
        49.50,
        premium_rate=0.15,
        lot_fee=3.0,
        sales_tax_rate=0.0825,
    )
    assert bid == 37.15


def test_external_market_value_derives_realistic_value_and_allocation_ceiling():
    record = {
        "identity": "upc:example",
        "identity_confidence": "high",
        "price_confidence": "high",
        "observed_at": "2026-09-26",
        "allocation_ratio": 0.60,
        "observations": [
            {"condition": "new", "price": 100, "source_label": "A", "url": "https://example.com/a"},
            {"condition": "new", "price": 120, "source_label": "B", "url": "https://example.com/b"},
        ],
    }
    derived = derive_market_valuation(
        record,
        condition="OPEN BOX",
        current_all_in=20,
        premium_rate=0.15,
        lot_fee=3.0,
        sales_tax_rate=0.0825,
    )
    assert derived["market_price_status"] == "verified_external"
    assert derived["verified_new_price"] == 110.0
    assert derived["current_new_average"] == 110.0
    assert derived["realistic_open_box_value"] == 82.5
    assert derived["market_reference_value"] == 82.5
    assert derived["max_all_in"] == 49.5
    assert derived["verified_max_bid"] == 37.15
    assert derived["verified_discount_pct"] == 75.8


def test_secondary_market_median_overrides_new_price_haircut():
    record = {
        "identity": "upc:example",
        "allocation_ratio": 0.50,
        "observations": [
            {"condition": "new", "price": 1000, "source_label": "New", "url": "https://example.com/new"},
            {"condition": "open_box", "price": 700, "source_label": "Open", "url": "https://example.com/open"},
            {"condition": "used", "price": 600, "source_label": "Used", "url": "https://example.com/used"},
        ],
    }
    summary = summarize_market_value(record)
    assert summary["open_box_used"]["median"] == 650.0

    derived = derive_market_valuation(record, condition="LIKE NEW", current_all_in=100)
    assert derived["market_reference_basis"] == "open_box_used_median"
    assert derived["market_reference_value"] == 650.0
    assert derived["max_all_in"] == 325.0
