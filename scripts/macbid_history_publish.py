"""Publish descriptive exact-cohort history in the existing public hunt catalog."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from deal_engine.historical_outcomes import summarize_outcomes, walk_forward_sold_prices

CATALOG = Path("site/catalog.json")
STATE = Path("results/macbid-public-history-state.json")
SEED = Path("data/macbid_public_outcome_seed.json")

def canonical(identity):
    kind, _, token = str(identity or "").partition(":")
    return "upc:" + token.upper() if kind in {"upc","asin"} and token else str(identity or "")

def summary(rows, fee):
    s = summarize_outcomes(rows, budget=100, **fee)
    return {k:s[k] for k in ("sample_lots","verified_sold","verified_unsold","unresolved",
                            "estimated_all_in_p25","estimated_all_in_p50","estimated_all_in_p75",
                            "estimated_all_in_p90")}

def enrich_history(catalog, state, seed):
    fee = {"premium_rate": catalog["buyer_premium_rate"], "lot_fee":catalog["lot_fee"],
           "sales_tax_rate":catalog["sales_tax_rate"]}
    scope = (state.get("latest_complete") or {}).get("scope_id")
    outcomes = [row for row in state.get("outcomes",[]) if scope and row.get("scope_id")==scope]
    pending = [row for row in state.get("pending",[]) if scope and row.get("scope_id")==scope]
    scans = state.get("coverage_epochs",{}).get(scope,[])
    seed_rows = seed.get("outcomes",[])
    legacy = [row for row in state.get("outcomes",[])+state.get("pending",[]) if row.get("scope_id")=="recovered-legacy-retail-floor-40"]
    cohorts = defaultdict(list)
    for row in outcomes + pending:
        key = (canonical(row.get("identity")), row.get("auction_location"), row.get("condition"))
        if all(key):
            cohorts[key].append(row)
    seed_cohorts = defaultdict(list)
    for row in seed_rows:
        if row.get("reconciliation_level") == "lot_detail_reconciled":
            key = (canonical(row.get("identity")),row.get("auction_location"),row.get("condition"))
            if all(key):
                seed_cohorts[key].append(row)
    for product in catalog.get("products",[]):
        identity = canonical(product.get("identity"))
        groups = []
        for location,condition in sorted({(lot.get("auction_location"),lot.get("condition")) for lot in product.get("lots",[]) if lot.get("auction_location") and lot.get("condition")}):
            key=(identity,location,condition)
            live, historical = cohorts.get(key,[]),seed_cohorts.get(key,[])
            if live or historical:
                groups.append({"location":location,"condition":condition,"prospective":summary(live,fee),
                               "selected_historical_sample":summary(historical,fee)})
        if groups:
            product["historical_acquisition"] = {"cohorts":groups,
               "note":"Exact identity, location and condition only. Estimated current fees; selected historical results are not a representative sample."}
    for profile in catalog.get("hunt_profiles",[]):
        hid=profile["id"]
        rows=[row for row in outcomes+pending if hid in (row.get("hunt_ids") or [])]
        profile["history_coverage"]={"verified_sold":sum(row.get("status")=="closed_sold_verified" for row in rows),
          "verified_unsold":sum(row.get("status")=="closed_unsold_verified" for row in rows),
          "unresolved":sum(row.get("status")=="missing_unresolved" for row in rows)}
    replay = walk_forward_sold_prices(outcomes, complete_scan_epochs=scans)
    catalog["historical_acquisition"] = {
        "schema":"macbid-public-history-summary-v1",
        "collector_status":state.get("collector_status","state_unavailable"),
        "scope_id":scope,"complete_scan_count":len(scans),"complete_days":len({e//86400 for e in scans}),
        "pending_overflow_count":state.get("pending_overflow_count",0),
        "prospective":summary(outcomes+pending,fee),
        "selected_historical_sample":summary(seed_rows,fee),
        "recovered_legacy_scope":summary(legacy,fee),
        "walk_forward":{k:v for k,v in replay.items() if k != "cases"},
        "minimum_training_samples":20,"minimum_complete_days":30,
        "fee_scenario":fee,"forecast_status":"evaluated" if replay["evaluated_cases"] else "insufficient_evidence",
        "note":"No purchase, sale probability or waiting-time estimate is inferred. Missing lots stay unresolved. Public history coverage is not market-wide."}
    return catalog

def main():
    catalog=json.loads(CATALOG.read_text())
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    seed=json.loads(SEED.read_text())
    doc=enrich_history(catalog,state,seed)
    compact=json.dumps(doc,separators=(",",":"),ensure_ascii=False)
    CATALOG.write_text(compact)
    Path("site/catalog.js").write_text("window.MACBID_CATALOG="+compact+";\n")
    Path("results/macbid-public-history-summary.json").write_text(json.dumps(doc["historical_acquisition"],indent=2))
    print("PUBLIC_HISTORY_SUMMARY",json.dumps(doc["historical_acquisition"]))

if __name__=="__main__":
    main()
