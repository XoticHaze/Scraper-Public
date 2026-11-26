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
    canonical_lot_url, lot_key, pending_closed_candidates, parse_closed_listing, reconcile_detail,
)

ARTIFACT = "macbid-public-history-state"
STATE = Path("results/macbid-public-history-state.json")
SNAPSHOT = Path("results/macbid-public-observations.json")
MAX_ROWS = 20000
MAX_AGE = 90 * 86400
MAX_AUCTIONS = 3
MAX_DETAIL = 12

def previous_state():
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
    return {"pending": [], "outcomes": [], "coverage_epochs": {}, "latest_complete": None}

def make_state(old, current, *, now):
    latest = old.get("latest_complete") or {}
    pending = {lot_key(row): row for row in old.get("pending", []) if
               row.get("source_epoch_utc", 0) >= now - MAX_AGE}
    outcomes = {lot_key(row): row for row in old.get("outcomes", []) if
                row.get("verified_epoch_utc", 0) >= now - MAX_AGE}
    for row in pending_closed_candidates(latest, current):
        key = lot_key(row)
        if key not in outcomes:
            pending.setdefault(key, row)
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
            "collector_status": "not_attempted"}

def collect(state):
    from playwright.sync_api import sync_playwright
    # Prefer the ice maker pilot, but reserve half the detail budget for all other hunts.
    eligible = [r for r in state["pending"] if canonical_lot_url(r) and str(r.get("auction_id", "")).isdigit()]
    pilot = [r for r in eligible if "ice-makers" in (r.get("hunt_ids") or [])]
    general = [r for r in eligible if r not in pilot]
    # Oldest last-attempt first, then original source epoch; avoid retry starvation.
    order = lambda r: (r.get("last_attempt_epoch_utc", 0), r.get("source_epoch_utc", 0))
    selected = sorted(pilot, key=order)[:MAX_DETAIL//2] + sorted(general, key=order)[:MAX_DETAIL//2]
    if not selected:
        state["collector_status"] = "no_due_candidates"
        return
    resolved = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
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
                state["collector_status"] = "robots_disallowed"
                break
            try:
                resp = page.goto(listing_url, wait_until="domcontentloaded", timeout=15000)
                if resp is None or resp.status in {401,403,429}:
                    state["collector_status"] = "source_access_restricted"
                    break
                if not resp.ok or page.url != listing_url:
                    continue
                page.locator("a[href*='/auction/']").first.wait_for(timeout=5000)
                anchors = page.locator("a[href*='/auction/']").evaluate_all(
                    "(els) => els.map(e => ({href:e.href, text:e.innerText}))")
            except Exception:
                state["collector_status"] = "source_unavailable"
                break
            for row in rows:
                now = int(time.time())
                row["last_attempt_epoch_utc"] = now
                href = canonical_lot_url(row)
                listing = next((p for a in anchors if (p := parse_closed_listing(row, href=a["href"], text=a["text"]))), None)
                if listing is None or not robots.can_fetch("*", href):
                    continue
                try:
                    resp = page.goto(href, wait_until="domcontentloaded", timeout=12000)
                    if resp is None or resp.status in {401,403,429}:
                        stop = True
                        state["collector_status"] = "source_access_restricted"
                        break
                    if not resp.ok or page.url != href:
                        continue
                    detail = page.locator("body").inner_text(timeout=5000)
                    result = reconcile_detail(row, listing, href=href, detail_text=detail,
                                              verified_epoch_utc=int(time.time()), scope_id=row["scope_id"])
                    if result:
                        resolved.append(result)
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
    old = previous_state()
    state = make_state(old, current, now=int(time.time()))
    # Do not query closing outcomes from a degraded scan.
    if current.get("coverage_complete"):
        collect(state)
    else:
        state["collector_status"] = "degraded_scan_no_collection"
    STATE.write_text(json.dumps(state, separators=(",", ":")))
    print(f"PUBLIC_HISTORY_STATE pending={len(state['pending'])} outcomes={len(state['outcomes'])} new={state.get('new_outcomes',0)} status={state['collector_status']} overflow={state['pending_overflow_count']}")

if __name__ == "__main__":
    main()
