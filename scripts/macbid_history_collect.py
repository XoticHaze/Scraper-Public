"""Bounded historical reconciliation using existing public-source scan workflow.

No account session, no bidding, no access bypass, no inferred outcomes.
Previous state is loaded from this repository's own 90-day public scan artifact.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from deal_engine.historical_reconciliation import (
    canonical_lot_url, lot_key, pending_closed_candidates, parse_closed_listing, reconcile_detail, detail_only_evidence,
)

from deal_engine.recovered_history import load_expanded_seed

ARTIFACT = "macbid-public-history-state"
STATE = Path("results/macbid-public-history-state.json")
SNAPSHOT = Path("results/macbid-public-observations.json")
MAX_ROWS = 20000
MAX_AGE = 90 * 86400
MAX_AUCTIONS = 3
MAX_DETAIL = 12

def previous_state(current):
    """Read only a prior public main-branch workflow's own state artifact."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo != "XoticHaze/Scraper-Public":
        raise RuntimeError("owning public repository required")
    raw = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/artifacts?name={ARTIFACT}&per_page=20"],
                                  text=True, timeout=30)
    rows = json.loads(raw).get("artifacts", [])
    for artifact in rows:
        run = artifact.get("workflow_run") or {}
        if artifact.get("name") != ARTIFACT or artifact.get("expired") or run.get("head_branch") != "main":
            continue
        rid = str(run.get("id") or "")
        if not rid.isdigit() or rid == os.environ.get("GITHUB_RUN_ID"):
            continue
        if artifact.get("size_in_bytes", 0) > 25_000_000:
            raise RuntimeError("history state exceeds bound")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["gh", "run", "download", rid, "--repo", repo, "--name", ARTIFACT, "--dir", tmp],
                           check=True, timeout=60, capture_output=True)
            path = Path(tmp) / STATE.name
            if not path.exists() or path.stat().st_size > 80_000_000:
                raise RuntimeError("invalid prior state artifact")
            doc = json.loads(path.read_text())
            if doc.get("schema") != "macbid-public-history-state-v1":
                raise RuntimeError("unknown prior state schema")
            return doc
    # Bootstrap from the already deployed 90-day observation artifact if it has
    # identical discovery scope. Older snapshots have no per-row source epoch.
    raw = subprocess.check_output(["gh", "api", f"repos/{repo}/actions/artifacts?name=macbid-public-observations&per_page=20"],
                                  text=True, timeout=30)
    for artifact in json.loads(raw).get("artifacts", []):
        run = artifact.get("workflow_run") or {}
        rid = str(run.get("id") or "")
        if artifact.get("name") != "macbid-public-observations" or artifact.get("expired") or run.get("head_branch") != "main" or not rid.isdigit() or rid == os.environ.get("GITHUB_RUN_ID"):
            continue
        if artifact.get("size_in_bytes",0) > 25_000_000:
            raise RuntimeError("prior observation exceeds bound")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["gh","run","download",rid,"--repo",repo,"--name","macbid-public-observations","--dir",tmp],
                           check=True,timeout=60,capture_output=True)
            path=Path(tmp)/SNAPSHOT.name
            if not path.exists() or path.stat().st_size > 80_000_000:
                raise RuntimeError("invalid prior observation artifact")
            prior=json.loads(path.read_text())
        if prior.get("schema")!="macbid-public-observation-v1" or not prior.get("coverage_complete"):
            continue
        epoch=prior.get("source_epoch_utc")
        if not isinstance(epoch,int) or epoch>=current.get("source_epoch_utc",0):
            continue
        prior_scope=prior.get("scope")
        if prior_scope is None:
            prior_scope={"filter":re.sub(r"expected_closing_utc:>\d+", "expected_closing_utc:>SCAN_EPOCH",str(prior.get("filter_by") or "")),
                "locations":sorted({row["auction_location"] for row in prior.get("observations",[]) if row.get("auction_location")})}
        if prior_scope != current.get("scope"):
            continue
        prior["scope"]=prior_scope
        prior["scope_id"]=current["scope_id"]
        for row in prior.get("observations",[]):
            row["source_epoch_utc"]=epoch
        return {"pending":[],"outcomes":[],"coverage_epochs":{prior["scope_id"]:[epoch]},"latest_complete":prior,
                "bootstrapped_from_observation_run":rid}
    return {"pending": [], "outcomes": [], "coverage_epochs": {}, "latest_complete": None}

def make_state(old, current, *, now, recovered_seed=None, expanded_seed=None):
    latest = old.get("latest_complete") or {}
    pending = {lot_key(row): row for row in old.get("pending", []) if
               row.get("source_epoch_utc", 0) >= now - MAX_AGE}
    outcomes = {lot_key(row): row for row in old.get("outcomes", []) if
                row.get("verified_epoch_utc", 0) >= now - MAX_AGE}
    seed_loaded = bool(old.get("recovered_seed_loaded"))
    if not seed_loaded and recovered_seed is not None:
        for row in recovered_seed.get("pending", []):
            key = lot_key(row)
            if all(key) and key not in outcomes and row.get("scope_id") == "recovered-legacy-retail-floor-40" and row.get("source_epoch_utc",0) >= now-MAX_AGE:
                pending.setdefault(key, row)
        seed_loaded=True
    expanded_loaded = bool(old.get("expanded_seed_loaded"))
    if not expanded_loaded and expanded_seed is not None:
        for row in expanded_seed:
            key = lot_key(row)
            if key not in outcomes and row["source_epoch_utc"] >= now - MAX_AGE:
                if key in pending:
                    # Preserve pilot attempts and add newly reconstructed hunt tags.
                    prior = pending[key]
                    if prior.get("scope_id") == row["scope_id"]:
                        pending[key] = {**row, **prior, "hunt_ids": sorted(set(row["hunt_ids"]) | set(prior.get("hunt_ids") or []))}
                else:
                    pending[key] = row
        expanded_loaded = True
    for row in pending_closed_candidates(latest, current):
        key = lot_key(row)
        if key not in outcomes:
            if key not in pending or pending[key].get("scope_id") != row.get("scope_id"):
                pending[key] = row
    # Reappearance invalidates a missing candidate; only an explicit closure is an outcome.
    if current.get("coverage_complete"):
        for row in current.get("observations", []):
            pending.pop(lot_key(row), None)
    # Oldest first; retain an explicit overflow counter instead of claiming full coverage.
    ordered = sorted(pending.values(), key=lambda row: (row.get("source_epoch_utc", 0), lot_key(row)))
    overflow = max(0, len(ordered) - MAX_ROWS)
    coverage = {k: sorted({e for e in v if e >= now-MAX_AGE}) for k,v in (old.get("coverage_epochs") or {}).items()}
    if current.get("coverage_complete"):
        latest = current
        scope = current.get("scope_id")
        if scope:
            coverage[scope] = sorted(set(coverage.get(scope, []) + [current["source_epoch_utc"]]))
    return {"schema": "macbid-public-history-state-v1", "generated_epoch_utc": now,
            "latest_complete": latest, "pending": ordered[:MAX_ROWS],
            "outcomes": list(outcomes.values())[-MAX_ROWS:], "coverage_epochs": coverage,
            "pending_overflow_count": int(old.get("pending_overflow_count") or 0) + overflow,
            "collector_status": "not_attempted", "recovered_seed_loaded": seed_loaded,
            "expanded_seed_loaded": expanded_loaded,
            "bootstrapped_from_observation_run": old.get("bootstrapped_from_observation_run")}

def select_candidates(state):
    """Reserve actual auction capacity for current scope, pilot and general backlog."""
    eligible = [r for r in state["pending"] if canonical_lot_url(r) and str(r.get("auction_id", "")).isdigit()]
    scope = (state.get("latest_complete") or {}).get("scope_id")
    pilot = lambda r: "ice-makers" in (r.get("hunt_ids") or [])
    current = lambda r: scope and r.get("scope_id") == scope
    order = lambda r: (r.get("last_attempt_epoch_utc", 0), r.get("source_epoch_utc", 0), lot_key(r))
    selected, keys, auctions = [], set(), set()
    def take(pool, limit):
        count = 0
        for row in sorted(pool, key=order):
            key = lot_key(row)
            if key in keys or (key[0] not in auctions and len(auctions) >= MAX_AUCTIONS):
                continue
            selected.append(row)
            keys.add(key)
            auctions.add(key[0])
            count += 1
            if count >= limit or len(selected) >= MAX_DETAIL:
                break
    # Pick a single auction in each lane before filling, to avoid exhausting all groups.
    for predicate in (current, pilot, lambda r: not pilot(r)):
        pool = [r for r in eligible if predicate(r) and lot_key(r) not in keys]
        if pool:
            first = min(pool, key=order)
            take([r for r in pool if lot_key(r)[0] == lot_key(first)[0]], 4)
    if len(selected) < MAX_DETAIL:
        take(eligible, MAX_DETAIL-len(selected))
    return selected

def collect(state):
    from playwright.sync_api import sync_playwright
    selected = select_candidates(state)
    state["collector_attempt_counts"] = {"selected": len(selected), "auction_pages": 0, "detail_pages": 0, "listing_missing": 0, "listing_unparsed": 0, "listing_scroll_advances": 0, "detail_only_evidence": 0, "detail_unverified": 0, "source_unavailable": 0, "robots_disallowed": 0}
    counts = state["collector_attempt_counts"]
    if not selected:
        state["collector_status"] = "no_due_candidates"
        return
    resolved = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(timezone_id="America/Chicago")
        # Robots must be readable and permit the requested public pages. No bypass.
        try:
            response = context.request.get("https://www.mac.bid/robots.txt", timeout=10000)
            robots = RobotFileParser()
            if response.status == 404:
                robots.parse([])
            elif response.ok:
                robots.parse(response.text().splitlines())
            else:
                state["collector_status"] = f"robots_unavailable_{response.status}"
                return
        except Exception:
            state["collector_status"] = "robots_unavailable"
            return
        page = context.new_page()
        groups = {}
        for row in selected:
            groups.setdefault(str(row["auction_id"]), []).append(row)
        stop = False
        for auction, rows in list(groups.items())[:MAX_AUCTIONS]:
            listing_url = f"https://www.mac.bid/past-auctions/{auction}"
            if not robots.can_fetch("*", listing_url):
                counts["robots_disallowed"] += 1
                state["collector_status"] = "robots_disallowed"
                break
            for row in rows:
                row["last_attempt_epoch_utc"] = int(time.time())
                row["last_attempt_status"] = "listing_requested"
            counts["auction_pages"] += 1
            try:
                resp = page.goto(listing_url, wait_until="domcontentloaded", timeout=15000)
                if resp is None or resp.status in {401,403,429}:
                    state["collector_status"] = "source_access_restricted"
                    break
                if not resp.ok or page.url != listing_url:
                    counts["source_unavailable"] += 1
                    for row in rows:
                        row["last_attempt_status"] = "listing_http_or_redirect"
                    continue
                page.locator("a[href*='/auction/']").first.wait_for(timeout=5000)
                locator = page.locator("a[href*='/auction/']")
                anchors = locator.evaluate_all("(els) => els.map(e => ({href:e.href, text:e.innerText}))")
                # Normal visible-page scrolling only. No hidden pagination endpoint,
                # synthetic URL, or access bypass. Stop on no additional rows.
                wanted = {canonical_lot_url(row) for row in rows}
                for _ in range(3):
                    if wanted.issubset({a["href"] for a in anchors}):
                        break
                    previous_count = len(anchors)
                    locator.last.scroll_into_view_if_needed(timeout=3000)
                    try:
                        page.wait_for_function(
                            "(n) => document.querySelectorAll(\"a[href*='/auction/']\").length > n",
                            arg=previous_count, timeout=2500)
                    except Exception:
                        break
                    anchors = locator.evaluate_all("(els) => els.map(e => ({href:e.href, text:e.innerText}))")
                    counts["listing_scroll_advances"] += 1
            except Exception:
                counts["source_unavailable"] += 1
                for row in rows:
                    row["last_attempt_status"] = "listing_source_unavailable"
                state["collector_status"] = "source_unavailable"
                break
            for row in rows:
                now = int(time.time())
                row["last_attempt_epoch_utc"] = now
                href = canonical_lot_url(row)
                matching = [a for a in anchors if a["href"] == href]
                listing = next((p for a in matching if (p := parse_closed_listing(row, href=a["href"], text=a["text"]))), None)
                if listing is None:
                    reason = "listing_unparsed" if matching else "listing_missing"
                    counts[reason] += 1
                    row["last_attempt_status"] = reason
                    # The exact previously observed public lot URL is already known.
                    # A direct detail may be independently useful descriptive evidence,
                    # but remains pending until the listing corroborates it.
                if not robots.can_fetch("*", href):
                    counts["robots_disallowed"] += 1
                    row["last_attempt_status"] = "detail_robots_disallowed"
                    continue
                counts["detail_pages"] += 1
                try:
                    resp = page.goto(href, wait_until="domcontentloaded", timeout=12000)
                    if resp is None or resp.status in {401,403,429}:
                        stop = True
                        state["collector_status"] = "source_access_restricted"
                        break
                    if not resp.ok or page.url != href:
                        counts["source_unavailable"] += 1
                        row["last_attempt_status"] = "detail_http_or_redirect"
                        continue
                    try:
                        page.wait_for_function(
                            """() => {const t=document.body.innerText;return /Mac\\.Bid ID:/i.test(t) && /Lot Number:/i.test(t) && /Auction Closed/i.test(t)}""",
                            timeout=5000)
                    except Exception:
                        counts["detail_unverified"] += 1
                        row["last_attempt_status"] = "detail_not_hydrated"
                        continue
                    detail = page.locator("body").inner_text(timeout=5000)
                    diagnostic = {}
                    checked = int(time.time())
                    result = reconcile_detail(row, listing, href=href, detail_text=detail,
                                              verified_epoch_utc=checked, scope_id=row["scope_id"], diagnostic=diagnostic)
                    if listing is None:
                        evidence = detail_only_evidence(row, href=href, detail_text=detail,
                                                        verified_epoch_utc=checked, scope_id=row["scope_id"])
                        if evidence:
                            row["detail_evidence"] = evidence
                            counts["detail_only_evidence"] += 1
                            row["last_attempt_status"] = "detail_only_pending_corroboration"
                            continue
                    if result:
                        resolved.append(result)
                    else:
                        counts["detail_unverified"] += 1
                        row["last_attempt_status"] = diagnostic.get("reason", "detail_unverified")
                        reason = row["last_attempt_status"]
                        counts[reason] = counts.get(reason, 0) + 1
                except Exception:
                    stop = True
                    state["collector_status"] = "source_unavailable"
                    break
            if stop:
                break
        browser.close()
    if state["collector_status"] == "not_attempted":
        state["collector_status"] = "bounded_public_pass"
    keys = {lot_key(r) for r in resolved}
    state["pending"] = [r for r in state["pending"] if lot_key(r) not in keys]
    state["outcomes"] = (state["outcomes"] + resolved)[-MAX_ROWS:]
    state["new_outcomes"] = len(resolved)

def main():
    current = json.loads(SNAPSHOT.read_text())
    old = previous_state(current)
    seed = json.loads(Path("data/macbid_recovered_pilot_pending.json").read_text())
    state = make_state(old, current, now=int(time.time()), recovered_seed=seed, expanded_seed=None if old.get("expanded_seed_loaded") else load_expanded_seed())
    # Do not query closing outcomes from a degraded scan.
    if current.get("coverage_complete"):
        collect(state)
    else:
        state["collector_status"] = "degraded_scan_no_collection"
    STATE.write_text(json.dumps(state, separators=(",", ":")))
    print("PUBLIC_HISTORY_ATTEMPTS " + json.dumps(state.get("collector_attempt_counts") or {}, sort_keys=True))
    print(f"PUBLIC_HISTORY_STATE pending={len(state['pending'])} outcomes={len(state['outcomes'])} new={state.get('new_outcomes',0)} status={state['collector_status']} overflow={state['pending_overflow_count']}")

if __name__ == "__main__":
    main()
