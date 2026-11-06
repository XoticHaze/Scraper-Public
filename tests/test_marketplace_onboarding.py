"""Contract tests for opt-in eBay and Best Buy onboarding. Fixture-only: no network."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from deal_engine.marketplace import (
    ebay_risk, normalize_ebay_item, normalize_bestbuy_products, normalize_bestbuy_open_box,
)
from deal_engine.marketplace.probes import SourceAccessError, get_bestbuy_sku, get_ebay_item

STAMP = datetime(2026, 11, 6, tzinfo=timezone.utc)


class MarketplaceOnboardingTests(unittest.TestCase):
    def ebay(self):
        return {
            "itemId": "v1|227505526667|0",
            "title": "AirPods 4 ANC",
            "price": {"value": "57.97", "currency": "USD"},
            "itemWebUrl": "https://www.ebay.com/itm/227505526667",
            "seller": {"username": "example", "feedbackScore": 5000,
                       "positiveFeedbackPercent": "99.8"},
            "returnTerms": {"returnsAccepted": False},
            "localizedAspects": [{"name": "Model", "value": "Apple EarPods"}],
            "image": {"imageUrl": "https://i.ebayimg.com/images/example.jpg"},
        }

    def test_ebay_mismatch_overrides_feedback(self):
        row = normalize_ebay_item(self.ebay(), observed_at=STAMP)
        self.assertEqual(row["risk"]["decision"], "PASS")
        self.assertIn("contradictory_product_model", row["risk"]["critical_flags"])
        self.assertIn("seller_no_returns", row["risk"]["warnings"])
        self.assertEqual(row["seller"]["positive_feedback_pct"], "99.8")

    def test_ebay_good_feedback_does_not_verify_authenticity(self):
        item = self.ebay()
        item["localizedAspects"] = [{"name": "Model", "value": "A3055"}]
        item["returnTerms"] = {"returnsAccepted": True}
        self.assertEqual(ebay_risk(item, expected_model_ids=["A3055"])["decision"], "REVIEW")
        self.assertEqual(ebay_risk(item)["authenticity_status"], "not_verified")

    def test_explicit_model_mismatch(self):
        item = self.ebay()
        item["localizedAspects"] = [{"name": "Model", "value": "A2190"}]
        self.assertEqual(ebay_risk(item, expected_model_ids=["A3055"])["decision"], "PASS")

    def test_reject_bad_ebay_url(self):
        item = self.ebay()
        item["itemWebUrl"] = "https://some-other-site.example/discount"
        with self.assertRaises(ValueError):
            normalize_ebay_item(item, observed_at=STAMP)

    def test_reject_non_usd(self):
        item = self.ebay()
        item["price"]["currency"] = "EUR"
        with self.assertRaises(ValueError):
            normalize_ebay_item(item)

    def test_bestbuy_products(self):
        rows = normalize_bestbuy_products({"products": [
            {"sku": 1234567, "name": "Widget", "salePrice": 59.99,
             "url": "https://api.bestbuy.com/click/abc/123/pdp?apiKey=secret"},
            {"sku": "bad", "name": "Bad", "salePrice": 19}
        ]}, observed_at=STAMP)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seller"]["type"], "retailer_direct")
        self.assertNotIn("secret", rows[0]["url"])
        self.assertEqual(rows[0]["risk"]["decision"], "REVIEW")

    def test_openbox_multiple_conditions(self):
        rows = normalize_bestbuy_open_box({"results": [{
            "sku": "1234567", "names": {"title": "Widget"},
            "links": {"web": "http://www.bestbuy.com/site/widget/1234567.p?apiKey=secret"},
            "offers": [{"condition": "excellent", "prices": {"current": 44.5}},
                       {"condition": "certified", "prices": {"current": 50.5}}]
        }]}, observed_at=STAMP)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["condition"], "open_box_excellent")
        self.assertEqual(rows[1]["condition"], "open_box_certified")
        self.assertEqual(rows[0]["url"], "https://www.bestbuy.com/site/widget/1234567.p")

    def test_empty_openbox_is_not_live_inventory(self):
        self.assertEqual(normalize_bestbuy_open_box({"results": []}), [])

    def test_credentials_fail_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SourceAccessError):
                get_ebay_item("227505526667")
            with self.assertRaises(SourceAccessError):
                get_bestbuy_sku("1234567")

    def test_source_registry_is_opt_in_and_has_unique_ids(self):
        import json
        from pathlib import Path
        registry = json.loads((Path(__file__).resolve().parents[1] / "config/marketplace_sources.json").read_text())
        ids = [source["id"] for source in registry["sources"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({"ebay", "bestbuy", "gsa", "govdeals", "publicsurplus",
                         "san_antonio_surplus", "gsa_fleet", "shopgoodwill"} <= set(ids))
        self.assertTrue(all(source["collector_enabled"] is False for source in registry["sources"]))

    def test_reject_unbounded_input(self):
        with self.assertRaises(ValueError):
            get_ebay_item("https://example.com")
        with self.assertRaises(ValueError):
            get_bestbuy_sku("1234; rm -rf")


if __name__ == "__main__":
    unittest.main()
