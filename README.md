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

## Current workload

`macbid-san-antonio-probe` opens the public MAC.BID San Antonio location page in headless Chromium and records only sanitized MAC.BID fetch/XHR metadata and JSON shape hints. It intentionally does **not** capture request headers, cookies, browser storage, or authentication state.

Target:

`https://www.mac.bid/locations/san-antonio`

The first objective is to identify the public inventory/search endpoint used by the site so later scans can query San Antonio and Schertz lots efficiently without depending on search-engine indexing.
