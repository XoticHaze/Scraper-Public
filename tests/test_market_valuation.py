from deal_engine.valuation import (
    derive_market_valuation,
    market_freshness,
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
            {"condition": "new", "price": 100, "source_label": "A", "url": "https://example.com/a", "observed_at": "2026-09-26"},
            {"condition": "new", "price": 120, "source_label": "B", "url": "https://example.com/b", "observed_at": "2026-09-26"},
        ],
    }
    derived = derive_market_valuation(
        record,
        condition="OPEN BOX",
        current_all_in=20,
        premium_rate=0.15,
        lot_fee=3.0,
        sales_tax_rate=0.0825,
        as_of="2026-09-27",
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
        "observed_at": "2026-09-26",
        "observations": [
            {"condition": "new", "price": 1000, "source_label": "New", "url": "https://example.com/new", "observed_at": "2026-09-26"},
            {"condition": "open_box", "price": 700, "source_label": "Open", "url": "https://example.com/open", "observed_at": "2026-09-26"},
            {"condition": "used", "price": 600, "source_label": "Used", "url": "https://example.com/used", "observed_at": "2026-09-26"},
        ],
    }
    summary = summarize_market_value(record)
    assert summary["open_box_used"]["median"] == 650.0

    derived = derive_market_valuation(
        record,
        condition="LIKE NEW",
        current_all_in=100,
        as_of="2026-09-27",
    )
    assert derived["market_reference_basis"] == "open_box_used_median"
    assert derived["market_reference_value"] == 650.0
    assert derived["max_all_in"] == 325.0


def test_market_freshness_classifies_fresh_aging_and_stale():
    assert market_freshness("2026-09-26", as_of="2026-09-27") == {
        "age_days": 1,
        "freshness": "fresh",
        "authoritative": True,
    }
    assert market_freshness("2026-09-10", as_of="2026-09-27")["freshness"] == "aging"
    stale = market_freshness("2026-08-01", as_of="2026-09-27")
    assert stale["freshness"] == "stale"
    assert stale["authoritative"] is False


def test_stale_external_value_does_not_issue_max_bid():
    record = {
        "identity": "upc:stale",
        "observed_at": "2026-08-01",
        "allocation_ratio": 0.50,
        "observations": [
            {"condition": "new", "price": 100, "source_label": "Old", "url": "https://example.com/old", "observed_at": "2026-08-01"},
        ],
    }
    derived = derive_market_valuation(
        record,
        condition="LIKE NEW",
        current_all_in=10,
        as_of="2026-09-27",
    )
    assert derived["market_price_status"] == "stale_external"
    assert derived["market_value_freshness"] == "stale"
    assert derived["market_value_authoritative"] is False
    assert derived["max_all_in"] is None
    assert derived["verified_max_bid"] is None


def test_protected_offer_comparison_requires_exact_live_and_complete_costs():
    from deal_engine.valuation import compare_protected_offers
    product = {"brand": "Aeitto", "model": "CB22C"}
    offer = {"brand": "Aeitto", "model": "CB22C", "condition": "open_box", "price": 100,
             "shipping": 10, "mandatory_fees": 0, "currency": "USD", "live_verified": True,
             "seller_verified": True, "return_days": 30, "availability": "in_stock",
             "observed_at": "2026-11-26", "url": "https://example.com/offer", "policy_url": "https://example.com/policy"}
    kwargs = dict(as_of="2026-11-26", sales_tax_rate=.0825, premium_rate=.15, lot_fee=3)
    result = compare_protected_offers(product, [offer, dict(offer, price=1, availability="out_of_stock"),
                                      dict(offer, price=2, model="CB22D")], **kwargs)
    assert len(result["offers"]) == 2
    assert result["best_protected_offer"]["price"] == 100
    assert result["max_auction_all_in"] == 59.54
    for change in ({"live_verified": False}, {"shipping": None}, {"return_days": None},
                   {"observed_at": "2026-11-23"}, {"observed_at": "2026-11-27"}):
        assert compare_protected_offers(product, [dict(offer, **change)], **kwargs)["max_auction_all_in"] is None


def test_freshness_is_per_observation_and_does_not_reuse_old_secondary_price():
    record = {"observed_at": "2026-11-26", "observations": [
        {"condition": "new", "price": 100, "observed_at": "2026-11-26"},
        {"condition": "open_box", "price": 999, "observed_at": "2026-09-01"},
        {"condition": "new", "price": 999, "observed_at": "2026-11-27"},
        {"condition": "new", "price": 999, "availability": "out_of_stock", "observed_at": "2026-11-26"}]}
    result = derive_market_valuation(record, condition="OPEN BOX", as_of="2026-11-26")
    assert result["verified_new_price"] == 100
    assert result["market_reference_value"] == 75
    assert result["market_value_source_count"] == 1
    record["observations"] = record["observations"][1:]
    assert derive_market_valuation(record, condition="OPEN BOX", as_of="2026-11-26")["verified_max_bid"] is None


def test_final_market_views_use_only_current_authoritative_value():
    from deal_engine.valuation import rebuild_market_views
    rows = [{"upc": "A", "deal_score": 1000, "market_price_status": "unverified"},
            {"upc": "B", "market_price_status": "verified_external", "market_value_authoritative": True,
             "verified_discount_pct": 50},
            {"upc": "C", "market_price_status": "stale_external", "verified_discount_pct": 99}]
    report = {"policy": {}}
    rebuild_market_views(report, active_inventory=rows)
    assert [r["upc"] for r in report["views"]["best_value"]] == ["B"]
    assert {r["upc"] for r in report["views"]["verification_queue"]} == {"A", "C"}
    assert report["market_publication"]["verified_lots"] == 1
