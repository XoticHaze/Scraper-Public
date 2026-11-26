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
    assert s["verified_sold"] == 7
    assert s["unresolved"] == 12
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


def test_walk_forward_never_uses_future_verifications_or_missing_coverage():
    from deal_engine.historical_outcomes import walk_forward_sold_prices
    day = 86400
    base = day * 100
    def row(i, observed, closed, known, price):
        return {"auction_id": str(i), "lot_number": "A", "identity": "upc:ABC",
                "auction_location": "San Antonio", "condition": "LIKE NEW",
                "training_eligible": True, "status": "closed_sold_verified",
                "reconciliation_level": "lot_detail_reconciled", "source_url": "https://www.mac.bid/past-auctions/1",
                "prediction_epoch_utc": observed, "closed_epoch_utc": closed,
                "verified_epoch_utc": known, "final_hammer": price}
    rows = [row(i, base+i, base+day+i, base+day+i+1, 50) for i in range(20)]
    cutoff = base + 40*day
    rows.append(row(100, cutoff, cutoff+day, cutoff+day+1, 80))
    rows.append(row(101, base, base+day, cutoff+day, 10000))
    coverage = [base+i*day+h*3600 for i in range(10, 40) for h in range(24)]
    result = walk_forward_sold_prices(rows, complete_scan_epochs=coverage)
    assert result["evaluated_cases"] == 1
    assert result["cases"][0]["training_samples"] == 20
    assert result["mean_absolute_error"] == 30
    assert walk_forward_sold_prices(rows, complete_scan_epochs=[])["evaluated_cases"] == 0
    assert walk_forward_sold_prices(rows, complete_scan_epochs=[base+i*day for i in range(10,40)])["evaluated_cases"] == 0
    assert result["observed_p25_p75_coverage"] == 0
    with pytest.raises(ValueError):
        walk_forward_sold_prices(rows, complete_scan_epochs=coverage, minimum_samples=1)


def test_exact_public_result_reconciliation_and_time_order():
    from datetime import datetime, timezone
    from deal_engine.historical_reconciliation import parse_closed_listing, reconcile_detail
    href = "https://www.mac.bid/auction/SAA2601-29-A1/lot/1040N"
    observed = int(datetime(2026, 1, 29, 20, tzinfo=timezone.utc).timestamp())
    verified = int(datetime(2026, 1, 30, 5, tzinfo=timezone.utc).timestamp())
    row = {"auction_id":"71686", "auction_number":"SAA2601-29-A1", "lot_number":"1040N",
           "lot_id":66737071, "upc":"B0FM3PD49H", "identity":"upc:B0FM3PD49H",
           "condition":"LIKE NEW", "auction_location":"San Antonio", "source_epoch_utc":observed,
           "current_bid":25, "hunt_ids":["ice-makers"]}
    text = "SenCre Ice Maker Machine Retails for $199.99 Lot #1040N Won for $50 Closed on 1/29/2026 at 8:16 PM"
    listing = parse_closed_listing(row, href=href, text=text)
    assert listing["final_hammer"] == 50
    assert parse_closed_listing(row, href=href.replace("1040N","1035N"), text=text) is None
    assert parse_closed_listing(row, href=href, text=text.replace("Won for $50","Current bid $50")) is None
    detail = "$50.00\n$199.99\nWinner saved 75.0% off retail price.\nAuction Closed 1/29/2026 at 8:16 PM\nCondition:\nLIKE NEW\nUPC:\nB0FM3PD49H\nLot Number:\nSAA2601-29-A1 / 1040N\nMac.Bid ID:\n66737071"
    outcome = reconcile_detail(row, listing, href=href, detail_text=detail, verified_epoch_utc=verified, scope_id="scope")
    assert outcome["training_eligible"]
    assert outcome["closed_epoch_utc"] == int(datetime(2026,1,30,2,16,59,tzinfo=timezone.utc).timestamp())
    assert reconcile_detail(row, listing, href=href, detail_text=detail.replace("B0FM3PD49H","B0WRONG000"), verified_epoch_utc=verified, scope_id="scope") is None
    assert reconcile_detail(row, listing, href=href, detail_text=detail.replace("$50.00","$51.00"), verified_epoch_utc=verified, scope_id="scope") is None
    diagnostic={}
    assert reconcile_detail(dict(row,inventory_id="12345678"), listing, href=href,
        detail_text=detail.replace("66737071","12345678"), verified_epoch_utc=verified, scope_id="scope", diagnostic=diagnostic) is None
    assert diagnostic["public_detail_id"]=="12345678" and diagnostic["matches_inventory_id"] is True
    assert diagnostic["reason"]=="lot_id_mismatch"
    assert reconcile_detail(dict(row, source_epoch_utc=verified), listing, href=href, detail_text=detail, verified_epoch_utc=verified, scope_id="scope") is None

def test_pending_only_same_complete_scope_and_no_inferred_outcomes():
    from scripts.macbid_history_collect import make_state
    row = {"auction_id":"1", "lot_number":"X", "source_epoch_utc":100, "expected_closing_utc":150}
    old = {"latest_complete":{"coverage_complete":True,"scope_id":"A","source_epoch_utc":100,"observations":[row]}}
    current = {"coverage_complete":True,"scope_id":"A","source_epoch_utc":200,"observations":[]}
    state = make_state(old, current, now=200)
    assert len(state["pending"]) == 1
    assert state["pending"][0]["status"] == "missing_unresolved"
    assert not state["outcomes"]
    assert not make_state(old,dict(current,scope_id="B"),now=200)["pending"]
    assert not make_state(old,dict(current,coverage_complete=False),now=200)["pending"]
    assert not make_state(state,dict(current,source_epoch_utc=300,observations=[row]),now=300)["pending"]


def test_history_publication_keeps_seed_separate_and_forecast_withheld():
    from scripts.macbid_history_publish import enrich_history
    seed = json.loads(Path("data/macbid_public_outcome_seed.json").read_text())
    catalog = {"buyer_premium_rate":.15,"lot_fee":3,"sales_tax_rate":.0825,
       "products":[{"identity":"asin:B0FM3PD49H","lots":[{"auction_location":"San Antonio","condition":"LIKE NEW"}]}],
       "hunt_profiles":[{"id":"ice-makers"}]}
    result=enrich_history(catalog,{},seed)
    hist=result["historical_acquisition"]
    assert hist["selected_historical_sample"]["verified_sold"] == 7
    assert hist["prospective"]["verified_sold"] == 0
    assert hist["forecast_status"] == "insufficient_evidence"
    assert hist["walk_forward"]["evaluated_cases"] == 0
    cohort=result["products"][0]["historical_acquisition"]["cohorts"][0]
    assert cohort["selected_historical_sample"]["verified_sold"] == 2
    assert cohort["prospective"]["verified_sold"] == 0


def test_recovered_pilot_is_not_mixed_with_current_scope_and_is_loaded_once():
    from scripts.macbid_history_collect import make_state
    seed=json.loads(Path("data/macbid_recovered_pilot_pending.json").read_text())
    assert len(seed["pending"]) == 11
    now=1795678809
    current={"scope_id":"new","coverage_complete":True,"source_epoch_utc":now,"observations":[]}
    out=make_state({},current,now=now,recovered_seed=seed)
    assert len(out["pending"]) == 11
    assert all(row["scope_id"]=="recovered-legacy-retail-floor-40" for row in out["pending"])
    assert out["coverage_epochs"]=={"new":[now]}
    assert not out["outcomes"]
    out["pending"]=[]
    assert not make_state(out,current,now=now,recovered_seed=seed)["pending"]


def test_hourly_scan_coverage_never_counts_partial_days_as_complete():
    from deal_engine.historical_outcomes import scan_coverage
    day=86400
    base=day*100
    epochs=[base+h*3600 for h in range(24)]
    assert scan_coverage(epochs)["qualified_days"] == 1
    assert scan_coverage(epochs[:-1])["qualified_days"] == 0
    assert scan_coverage(epochs, as_of=base+23*3600+30)["qualified_days"] == 0
    result=scan_coverage(epochs+[base+3*day])
    assert result["observed_days"]==2
    assert result["qualified_days"]==1
    assert result["maximum_gap_seconds"]==49*3600


def test_detail_only_evidence_does_not_become_training_outcome():
    from datetime import datetime, timezone
    from deal_engine.historical_reconciliation import detail_only_evidence
    href="https://www.mac.bid/auction/SAA2601-29-A1/lot/1040N"
    observed=int(datetime(2026,1,29,20,tzinfo=timezone.utc).timestamp())
    verified=int(datetime(2026,1,30,5,tzinfo=timezone.utc).timestamp())
    row={"auction_id":"71686","auction_number":"SAA2601-29-A1","lot_number":"1040N",
         "lot_id":66737071,"upc":"B0FM3PD49H","identity":"upc:B0FM3PD49H",
         "condition":"LIKE NEW","auction_location":"San Antonio","source_epoch_utc":observed}
    detail="$50.00\n$199.99\nWinner saved 75.0% off retail price.\nAuction Closed 1/29/2026 at 8:16 PM\nCondition:\nLIKE NEW\nUPC:\nB0FM3PD49H\nLot Number:\nSAA2601-29-A1 / 1040N\nMac.Bid ID:\n66737071"
    kwargs=dict(href=href,verified_epoch_utc=verified,scope_id="scope")
    evidence=detail_only_evidence(row,detail_text=detail,**kwargs)
    assert evidence["reported_hammer"] == 50
    assert evidence["status"] == "detail_only_sold"
    assert evidence["training_eligible"] is False
    assert detail_only_evidence(row,detail_text=detail.replace("B0FM3PD49H","B0WRONG000"),**kwargs) is None
    assert detail_only_evidence(row,detail_text=detail.replace("Winner saved","Current bid"),**kwargs) is None


def test_expanded_seed_and_selection():
    from deal_engine.recovered_history import load_expanded_seed
    from scripts.macbid_history_collect import make_state, select_candidates
    rows=load_expanded_seed()
    assert len(rows)==2617
    assert all(r["status"]=="missing_unresolved" and "final_hammer" not in r for r in rows)
    assert any("ice-makers" in r["hunt_ids"] for r in rows)
    now=1795697782
    current={"scope_id":"new","coverage_complete":True,"source_epoch_utc":now,"observations":[]}
    state=make_state({},current,now=now,expanded_seed=rows)
    assert len(state["pending"])==2617 and not state["outcomes"]
    selected=select_candidates(state)
    assert 0<len(selected)<=12 and len({r["auction_id"] for r in selected})<=3
    assert any("ice-makers" in r["hunt_ids"] for r in selected)
    assert any("ice-makers" not in r["hunt_ids"] for r in selected)
    state["pending"]=[]
    assert not make_state(state,current,now=now,expanded_seed=rows)["pending"]
