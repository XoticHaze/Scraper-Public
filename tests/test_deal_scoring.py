from datetime import datetime, timezone

from deal_engine.scoring import (
    estimated_pre_tax_total,
    hours_until_close,
    provisional_max_bid,
    score_lot,
)


def test_fee_math():
    assert estimated_pre_tax_total(50, premium_rate=0.15, lot_fee=3) == 60.5


def test_zero_bid_is_valid_price():
    scored = score_lot(
        {
            "condition": "LIKE NEW",
            "retail_price": 100,
            "current_bid": 0,
            "unique_bidders": 0,
            "total_bids": 0,
            "expected_close_date": "2026-09-10",
        }
    )
    assert scored["estimated_pre_tax_total"] == 3.0
    assert "missing usable retail/current bid" not in scored["reasons"]


def test_provisional_ceiling_is_condition_aware():
    like_new = provisional_max_bid(200, "LIKE NEW", premium_rate=0.15, lot_fee=3)
    open_box = provisional_max_bid(200, "OPEN BOX", premium_rate=0.15, lot_fee=3)
    assert like_new == 58.26
    assert open_box == 40.87
    assert like_new > open_box


def test_hours_until_close_iso():
    now = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    assert hours_until_close("2026-09-09T06:00:00Z", now=now) == 6.0


def test_date_only_close_does_not_invent_midnight():
    now = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    assert hours_until_close("2026-09-09", now=now) is None


def test_like_new_low_bid_scores_above_open_box_same_bid():
    base = {
        "retail_price": 240,
        "current_bid": 5,
        "unique_bidders": 2,
        "total_bids": 3,
        "expected_close_date": "2026-09-10T00:00:00Z",
    }
    now = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    like_new = score_lot({**base, "condition": "LIKE NEW"}, now=now)
    open_box = score_lot({**base, "condition": "OPEN BOX"}, now=now)
    assert like_new["deal_score"] > open_box["deal_score"]


def test_low_retail_is_penalized():
    now = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    cheap = score_lot(
        {
            "condition": "LIKE NEW",
            "retail_price": 20,
            "current_bid": 1,
            "unique_bidders": 0,
            "total_bids": 0,
            "expected_close_date": "2026-09-10T00:00:00Z",
        },
        low_value_retail_floor=40,
        now=now,
    )
    assert "low stated retail" in cheap["reasons"]
