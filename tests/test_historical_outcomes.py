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
    assert s["verified_sold"] == 19
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
