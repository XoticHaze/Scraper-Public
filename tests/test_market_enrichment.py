from deal_engine.market_enrichment import (
    extract_structured_prices,
    identity_kind,
    merged_market_records,
    reject_price_outliers,
    select_observation_price,
)


def test_identity_kind_distinguishes_asin_gtin_and_model():
    assert identity_kind("B0BZSD2L1W") == "asin"
    assert identity_kind("034138840887") == "gtin"
    assert identity_kind("UHD35STx") == "model"


def test_jsonld_requires_exact_identity_unless_url_is_exact():
    html = """
    <script type="application/ld+json">
    {"@type":"Product","name":"Example","gtin12":"034138840887",
     "offers":{"@type":"Offer","price":"149.99","priceCurrency":"USD"}}
    </script>
    """
    assert extract_structured_prices(html, identity="034138840887") == [
        {"price": 149.99, "condition": "new", "name": "Example"}
    ]
    assert extract_structured_prices(html, identity="000000000000") == []
    assert extract_structured_prices(
        html, identity="B0EXACT123", identity_in_url=True
    )[0]["price"] == 149.99


def test_labeled_price_is_allowed_only_on_exact_identity_url():
    html = "<html><body>Current Price: $134.99</body></html>"
    assert select_observation_price(
        html,
        identity="B0BZSD2L1W",
        identity_in_url=True,
        price_labels=["current price"],
    ) == (134.99, "labeled")
    assert select_observation_price(
        html,
        identity="B0BZSD2L1W",
        identity_in_url=False,
        price_labels=["current price"],
    ) == (None, "none")


def test_outlier_filter_rejects_absurd_single_listing():
    rows = [
        {"price": 100, "url": "https://a.example/x"},
        {"price": 110, "url": "https://b.example/x"},
        {"price": 999, "url": "https://c.example/x"},
    ]
    assert [row["price"] for row in reject_price_outliers(rows)] == [100, 110]


def test_runtime_merge_keeps_previous_observation_but_manual_policy_wins():
    previous = {
        "schema": "macbid-market-values-v1",
        "version": 2,
        "defaults": {"default_allocation_ratio": 0.9},
        "enrichment_attempts": {"upc:B0MISS0001": {"attempted_epoch": 123, "successful": False}},
        "valuations": [{
            "identity": "upc:B0TEST0001",
            "allocation_ratio": 0.9,
            "observations": [{
                "condition": "new", "price": 90, "source_label": "Runtime",
                "url": "https://runtime.example/item", "observed_at": "2026-09-27",
            }],
        }],
    }
    canonical = {
        "schema": "macbid-market-values-v1",
        "version": 2,
        "defaults": {"default_allocation_ratio": 0.65},
        "valuations": [{
            "identity": "upc:B0TEST0001",
            "allocation_ratio": 0.5,
            "risk_note": "manual",
            "observations": [{
                "condition": "new", "price": 100, "source_label": "Manual",
                "url": "https://manual.example/item", "observed_at": "2026-09-26",
            }],
        }],
    }
    merged = merged_market_records(canonical, previous)
    row = merged["valuations"][0]
    assert merged["defaults"]["default_allocation_ratio"] == 0.65
    assert row["allocation_ratio"] == 0.5
    assert row["risk_note"] == "manual"
    assert len(row["observations"]) == 2
    assert row["price_confidence"] == "high"
    assert merged["enrichment_attempts"]["upc:B0MISS0001"]["successful"] is False
