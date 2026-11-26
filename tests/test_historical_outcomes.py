import json
from pathlib import Path

import pytest

from deal_engine.historical_outcomes import summarize_outcomes


def test_real_seed_and_duplicate_guard():
    data = json.loads(Path("data/macbid_public_outcome_seed.json").read_text())
    rows = data["outcomes"]
    kw = dict(budget=100, premium_rate=.15, lot_fee=3, sales_tax_rate=.0825)
    s = summarize_outcomes(rows + [rows[0]], **kw)
    assert s["sample_lots"] == 20
    assert s["verified_sold"] == 2
    assert s["unresolved"] == 17
    assert s["verified_unsold"] == 1
    assert s["market_probability"] is None and s["expected_wait"] is None
    with pytest.raises(ValueError, match="conflicting"):
        summarize_outcomes(rows + [dict(rows[0], final_hammer=1)], **kw)


def test_missing_is_not_sold():
    s = summarize_outcomes([{"auction_id":"1","lot_number":"A","status":"missing_unresolved",
                              "final_hammer":5}], budget=100, premium_rate=.15,
                           lot_fee=3, sales_tax_rate=.0825)
    assert s["verified_sold"] == 0 and s["unresolved"] == 1
    assert s["estimated_all_in_p50"] is None


def test_snapshot_observed_open_dedupe_and_fallback():
    from deal_engine.historical_observations import build_snapshot
    lot = {"auction_id": "1", "auction_number": "A", "lot_id": 2, "current_bid": 0,
           "account_email": "do-not-collect", "expected_closing_utc": 200}
    report = {"scan": {"scan_epoch_utc": 100, "inventory_source_epoch_utc": 100, "complete": True},
              "inventory": [lot, lot]}
    catalog = {"inventory_source_epoch_utc": 100, "products": [{"identity": "upc:ABC",
                  "hunt_ids": ["ice-makers"], "lots": [lot]}]}
    out = build_snapshot(report, catalog)
    assert out["coverage_complete"] and out["observed_lots"] == 1
    assert out["observations"][0]["current_bid"] == 0
    assert out["observations"][0]["status"] == "observed_open"
    assert out["observations"][0]["hunt_ids"] == ["ice-makers"]
    assert "account_email" not in out["observations"][0]
    report["scan"]["degraded_inventory_source"] = True
    assert build_snapshot(report, catalog)["observations"] == []
