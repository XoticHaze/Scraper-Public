from scripts.macbid_postprocess import vehicle_catalog_cache_valid


def test_rejects_fee_sized_cached_vehicle_price():
    assert vehicle_catalog_cache_valid({"vehicles": [{"price": 225}]}) is False


def test_rejects_missing_or_non_numeric_cached_vehicle_price():
    assert vehicle_catalog_cache_valid({"vehicles": [{"price": None}]}) is False
    assert vehicle_catalog_cache_valid({"vehicles": [{"price": "call for price"}]}) is False


def test_accepts_plausible_cached_vehicle_prices():
    assert vehicle_catalog_cache_valid(
        {"vehicles": [{"price": 22491}, {"price": 23651}, {"price": 27000}]}
    ) is True


def test_accepts_empty_fallback_catalog_contract():
    assert vehicle_catalog_cache_valid({"vehicles": []}) is True
