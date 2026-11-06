"""Official GSA API contract fixtures. No network, invented fixture labels are not live data."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from deal_engine.marketplace.gsa import (
    GSASourceError, _records, normalize_gsa_auctions, build_gsa_catalog, fetch_gsa_auctions,
)

STAMP = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)


class GSASourceTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "SaleNo": "41QSCI123", "LotNo": 3, "ItemName": "UPS BATTERY BACKUP",
            "AuctionStatus": "A", "AucEndDt": "2026-11-10",
            "HighBidAmount": "35.00", "Reserve": "100",
            "BiddersCount": 2, "PropertyCity": "San Antonio",
            "PropertyState": "TX", "AgencyName": "Federal Agency",
            "ItemDescURL": "https://gsaauctions.gov/auction-item/123?tracking=abc",
            "ImageURL": "https://gsaauctions.gov/image/x.jpg",
        }

    def test_gsa_lot_normalization_and_time_precision(self):
        result = normalize_gsa_auctions({"data": [self.row]}, observed_at=STAMP, state="TX")
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["offer_id"], "gsa:41QSCI123:3")
        self.assertEqual(row["current_bid"], 35)
        self.assertEqual(row["closing_date"], "2026-11-10")
        self.assertIsNone(row["closing_time"])
        self.assertIsNone(row["verified_all_in_total"])
        self.assertIsNone(row["max_bid"])
        self.assertEqual(row["url"], "https://gsaauctions.gov/auction-item/123")

    def test_wont_invent_deal_from_other_location(self):
        self.assertEqual(normalize_gsa_auctions([self.row], state="CA"), [])

    def test_inactive_preview_excluded(self):
        r = dict(self.row, AuctionStatus="P")
        self.assertEqual(normalize_gsa_auctions([r]), [])

    def test_unrecognized_schema_fails_closed(self):
        with self.assertRaises(GSASourceError):
            _records({"error": "rate_limited"})
        with self.assertRaises(GSASourceError):
            _records({"data": [{"other": "fake"}]})

    def test_uncertain_identity_rejected_and_no_deduped_duplicate(self):
        bad = dict(self.row, SaleNo="*bad sale*")
        result = normalize_gsa_auctions([bad, self.row, dict(self.row)])
        self.assertEqual(len(result), 1)

    def test_external_link_not_trusted(self):
        row = dict(self.row, ItemDescURL="https://phishing.example/x?api_key=secret",
                   ImageURL="https://phishing.example/x.jpg")
        parsed = normalize_gsa_auctions([row])[0]
        self.assertIsNone(parsed["url"])
        self.assertIsNone(parsed["image_url"])

    def test_missing_bid_not_free(self):
        row = dict(self.row, HighBidAmount=None)
        self.assertIsNone(normalize_gsa_auctions([row])[0]["current_bid"])

    def test_catalog_preserves_observation_timestamp(self):
        result = build_gsa_catalog([self.row], state="TX", observed_at=STAMP)
        self.assertEqual(result["source_status"], "verified_live_api_response")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["observed_at"], "2026-11-06T18:00:00+00:00")

    def test_demo_not_automatic(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(GSASourceError):
                fetch_gsa_auctions()

    def test_us_date_without_time(self):
        row = dict(self.row, AucEndDt="11/10/2026")
        self.assertEqual(normalize_gsa_auctions([row])[0]["closing_date"], "2026-11-10")


if __name__ == "__main__":
    unittest.main()
