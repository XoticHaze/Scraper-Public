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

`XoticHaze/Scraper` is the separate private repository reserved for future authenticated/account-state work. The public deal engine must not depend on it.

## MAC.BID deal engine

The primary workload is now a category-agnostic local bargain engine rather than a lock-specific scraper.

Default market scope:

- San Antonio
- Schertz

Default condition policy:

- prefer `LIKE NEW`
- allow `OPEN BOX`
- exclude `DAMAGED`

The engine bootstraps MAC.BID's public Typesense search contract from the San Antonio location page, keeps only the local open-inventory query, expands it to San Antonio + Schertz, scans the catalog, and ranks the results.

Primary views:

- `ending_soon` — earliest public `expected_close_date` first
- `best_value` — deterministic score from condition, current bid, stated retail spread, bidder competition, and urgency
- `low_competition` — fewest bidders/bids first, using value score as a tiebreaker

Fee math currently uses MAC.BID's public 15% buyer premium plus $3 lot fee. Provisional max bids are intentionally conservative and are explicitly marked as based only on MAC.BID's stated retail until exact model and external market-price verification are added.

Configuration lives in `config/macbid_deal_engine.json`.

The first-stage engine is inventory-first. Direct searches and category/brand views should be applied over the same local inventory snapshot instead of spawning one scraper per keyword.

## Discovery probes

Earlier probe workflows remain as diagnostic tools for MAC.BID network/search changes. They capture only sanitized public metadata and do not capture request headers, cookies, browser storage, or authentication state.
