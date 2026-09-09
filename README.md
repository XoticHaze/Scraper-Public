# Scraper-Public

Public GitHub Actions compute for browser/network probes and scraping workloads.

## Authority and privacy boundary

This repository is **public compute**, not a declaration that workload inputs, session material, or results are public.

Default rules:

- Public targets and public, non-sensitive results may run directly.
- Never print or persist cookies, authorization headers, browser storage, access tokens, account identifiers, or other session material.
- Any future non-public input must use a run-bound encrypted capsule pattern before it reaches public compute.
- Private or sensitive outputs must be returned only as encrypted envelopes or deterministic sanitized receipts.
- Public workflows have execution authority only. They are not authoritative storage for private project state.
- Workflows should use the minimum GitHub token permissions required.

The encrypted transport pattern is modeled after `XoticHaze/research-compute-public-`: one-run X25519 recipient keys generated inside the runner, run-bound authenticated ciphertext, fixed consumers, sanitized receipts, and deletion of transient private material after execution.

`XoticHaze/Scraper` is the separate **private** repository reserved for future authenticated/account-state work. The public deal engine does not depend on it.

## MAC.BID deal engine

The primary workload is a category-agnostic local bargain engine rather than a lock-specific scraper.

Default market scope:

- San Antonio
- Schertz

Default condition policy:

- prefer `LIKE NEW`
- allow `OPEN BOX`
- exclude `DAMAGED`
- exclude pallets unless explicitly enabled
- suppress listings below a configurable stated-retail floor

The engine bootstraps MAC.BID's public Typesense search contract from the San Antonio location page, keeps only the local open-inventory query, expands it to San Antonio + Schertz, scans the complete eligible catalog, scores lots, collapses duplicate products, and builds a bounded market-verification queue.

### Exact ending-soonest authority

A browser probe of MAC.BID's own `Ending Soonest` control confirmed the native search contract:

```text
filter: expected_closing_utc > current epoch
sort:   expected_closing_utc:asc,ranking_weight:desc
```

The deal engine now uses that exact public epoch field rather than inventing a time from MAC.BID's date-only `expected_close_date`. It rechecks the epoch at final ranking so lots that expire during a scan are not surfaced as active.

### Primary views

- `ending_soon` — exact MAC.BID closing timestamp ascending
- `best_value` — deterministic discovery score from condition, current bid, stated-retail spread, bidder competition, and urgency
- `low_competition` — fewest bidders/bids first, using value as a tiebreaker
- `verification_queue` — unique high-ranked products that still require exact-model and real-market-price validation before a bid recommendation

Repeated copies of the same product are collapsed into one primary candidate with alternative lots attached, so a single product cannot flood the surface.

Fee math currently uses MAC.BID's public **15% buyer premium + $3 lot fee** and is labeled pre-tax. Provisional max bids are intentionally conservative and explicitly marked as based only on MAC.BID's stated retail until exact product/model and external market-price verification are available.

Configuration lives in `config/macbid_deal_engine.json`.

The first-stage engine is inventory-first. Direct searches, brands, categories, and future personal-interest overlays should be applied over the same local inventory snapshot instead of spawning one scraper per keyword.

## Account layer

Account integration is intentionally deferred. Future saved/watchlisted lots, search history, bids/wins, or other personal MAC.BID state belong in private `XoticHaze/Scraper` and should feed only the minimum needed preference/state signal into the public deal engine through the encrypted transport boundary.

## Discovery probes

Earlier probe workflows remain as diagnostic tools for MAC.BID network/search changes. They capture only sanitized public metadata and do not capture request headers, cookies, browser storage, or authentication state.
