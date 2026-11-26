"""Publish descriptive exact-cohort history in the existing public hunt catalog."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from deal_engine.historical_reconciliation import canonical_lot_url
from deal_engine.market_enrichment import identity_kind
from deal_engine.bid_history import aggregate_tracks, track_summary
from deal_engine.historical_reconciliation import lot_key
from deal_engine.historical_outcomes import summarize_outcomes, walk_forward_sold_prices, scan_coverage

CATALOG = Path("site/catalog.json")
STATE = Path("results/macbid-public-history-state.json")
SEED = Path("data/macbid_public_outcome_seed.json")

def canonical(identity):
    kind, _, token = str(identity or "").partition(":")
    return "upc:" + token.upper() if kind in {"upc","asin"} and identity_kind(token) in {"asin","gtin"} else ""

def summary(rows, fee):
    s = summarize_outcomes(rows, budget=100, **fee)
    return {k:s[k] for k in ("sample_lots","verified_sold","verified_unsold","unresolved",
                            "estimated_all_in_p25","estimated_all_in_p50","estimated_all_in_p75",
                            "estimated_all_in_p90")}

def recent_closes(rows, limit=5):
    """Small public projection, source URLs derived from previously captured lot identity."""
    result=[]
    for row in sorted(rows,key=lambda r:r.get("closed_epoch_utc") or 0,reverse=True):
        if row.get("status") not in {"closed_sold_verified","closed_unsold_verified"} or row.get("reconciliation_level")!="lot_detail_reconciled":
            continue
        href=canonical_lot_url(row)
        if not href or href!=row.get("lot_source_url"):
            continue
        result.append({"lot_url":href,"lot_number":row["lot_number"],"auction_number":row["auction_number"],
                       "closed_epoch_utc":row.get("closed_epoch_utc"),"final_hammer":row.get("final_hammer"),
                       "status":row["status"],"condition":row.get("condition"),
                       "identity":canonical(row.get("identity")) or None,
                       "scope":"recovered_legacy" if row.get("scope_id")=="recovered-legacy-retail-floor-40" else "selected_sample" if not row.get("scope_id") else "prospective"})
        if len(result)>=limit:
            break
    return result

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
    legacy_cohorts = defaultdict(list)
    for row in legacy:
        key=(canonical(row.get("identity")),row.get("auction_location"),row.get("condition"))
        if all(key) and key[0].startswith("upc:"):
            legacy_cohorts[key].append(row)
    seed_cohorts = defaultdict(list)
    for row in seed_rows:
        if row.get("reconciliation_level") == "lot_detail_reconciled":
            key = (canonical(row.get("identity")),row.get("auction_location"),row.get("condition"))
            if all(key):
                seed_cohorts[key].append(row)
    bid_history=state.get("bid_history") or {}
    tracks=bid_history.get("tracks",{}) if bid_history.get("scope_id")==scope else {}
    for product in catalog.get("products",[]):
        for lot in product.get("lots",[]):
            track=tracks.get(":".join(lot_key(lot)))
            expected=[str(lot.get("inventory_id") or ""),str(product.get("identity") or ""),str(lot.get("condition") or ""),str(lot.get("auction_location") or "")]
            if track and track["identity_fields"]==expected:
                lot["observed_bid_history"]=track_summary(track)
        identity = canonical(product.get("identity"))
        groups = []
        for location,condition in sorted({(lot.get("auction_location"),lot.get("condition")) for lot in product.get("lots",[]) if lot.get("auction_location") and lot.get("condition")}):
            key=(identity,location,condition)
            live, historical = cohorts.get(key,[]),seed_cohorts.get(key,[])
            recovered = legacy_cohorts.get(key,[])
            if live or historical or recovered:
                groups.append({"location":location,"condition":condition,"prospective":summary(live,fee),
                               "selected_historical_sample":summary(historical,fee),"recovered_legacy_scope":summary(recovered,fee),
                               "recent_verified_closes":recent_closes(live+recovered+historical)})
        if groups:
            product["historical_acquisition"] = {"cohorts":groups,
               "note":"Exact identity, location and condition only. Estimated current fees; selected historical results are not a representative sample."}
    for profile in catalog.get("hunt_profiles",[]):
        hid=profile["id"]
        rows=[row for row in outcomes+pending if hid in (row.get("hunt_ids") or [])]
        recovered = [row for row in legacy if hid in (row.get("hunt_ids") or [])]
        profile["recovered_legacy_history"] = summary(recovered,fee)
        profile["observed_bid_history"]=aggregate_tracks(r for r in tracks.values() if hid in r.get("hunt_ids",[]))
        profile["recent_verified_closes"] = recent_closes(rows+recovered)
        profile["history_coverage"]={"verified_sold":sum(row.get("status")=="closed_sold_verified" for row in rows),
          "verified_unsold":sum(row.get("status")=="closed_unsold_verified" for row in rows),
          "unresolved":sum(row.get("status")=="missing_unresolved" for row in rows)}
    replay = walk_forward_sold_prices(outcomes, complete_scan_epochs=scans)
    coverage = scan_coverage(scans, as_of=catalog.get("generated_epoch_utc"))
    catalog["historical_acquisition"] = {
        "schema":"macbid-public-history-summary-v1",
        "collector_status":state.get("collector_status","state_unavailable"),
        "predecessor_receipt":state.get("predecessor_receipt"),
        "scope_id":scope,"complete_scan_count":len(scans),"complete_days":coverage["qualified_days"],
        "observed_days":coverage["observed_days"],"coverage":coverage,
        "pending_overflow_count":state.get("pending_overflow_count",0),
        "observed_bid_history":{**aggregate_tracks(tracks.values()),"snapshot_count":len(bid_history.get("snapshot_epochs",[])),
            "point_drops":bid_history.get("point_drops",0),"track_drops":bid_history.get("track_drops",0),
            "identity_conflicts":len(bid_history.get("conflicts",{})),"bootstrap_failures":bid_history.get("bootstrap_failures",0)},
        "collector_attempt_counts":state.get("collector_attempt_counts",{}),
        "pending_detail_only_count":sum(bool(row.get("detail_evidence")) for row in state.get("pending",[])),
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
