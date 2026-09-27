from deal_engine.catalog_fallback import (
    catalog_age_seconds,
    fallback_catalog_is_usable,
    inventory_from_ui_catalog,
)


def catalog():
    return {
        "schema": "macbid-hunt-ui-v1",
        "generated_epoch_utc": 1000,
        "products": [
            {
                "name": "800W Solar Panel",
                "brand": "Example",
                "category": "Solar",
                "upc": "B0EXAMPLE1",
                "model": "PV800",
                "retail_price": 799,
                "image_url": "https://example.test/panel.jpg",
                "lots": [
                    {
                        "lot_id": "open",
                        "condition": "LIKE NEW",
                        "current_bid": 10,
                        "expected_closing_utc": 2000,
                    },
                    {
                        "lot_id": "closed",
                        "condition": "OPEN BOX",
                        "current_bid": 5,
                        "expected_closing_utc": 900,
                    },
                ],
            }
        ],
    }


def test_catalog_age_uses_published_generation_time():
    assert catalog_age_seconds(catalog(), 1120) == 120


def test_fallback_rehydrates_product_identity_fields_and_drops_closed_lots():
    rows = inventory_from_ui_catalog(catalog(), now_epoch=1100)
    assert len(rows) == 1
    assert rows[0]["lot_id"] == "open"
    assert rows[0]["product_name"] == "800W Solar Panel"
    assert rows[0]["upc"] == "B0EXAMPLE1"
    assert rows[0]["retail_price"] == 799


def test_recent_catalog_is_usable_but_old_catalog_is_rejected():
    assert fallback_catalog_is_usable(
        catalog(), now_epoch=1100, max_age_seconds=3600
    ) == (True, 100)
    assert fallback_catalog_is_usable(
        catalog(), now_epoch=5000, max_age_seconds=3600
    ) == (False, 4000)


def test_wrong_schema_is_not_usable():
    bad = catalog()
    bad["schema"] = "other"
    assert fallback_catalog_is_usable(
        bad, now_epoch=1100, max_age_seconds=3600
    )[0] is False
