# Scraper-Public

## MAC.BID Hunt

**Live app:** https://xotichaze.github.io/Scraper-Public/

**Finds & Watchlists:** https://xotichaze.github.io/Scraper-Public/finds.html

**Run a fresh scan:** https://github.com/XoticHaze/Scraper-Public/actions/workflows/macbid-deal-engine.yml

**Repository:** https://github.com/XoticHaze/Scraper-Public

The repository is the compute/control plane and GitHub Pages is the persistent browser surface:

```text
GitHub Actions
  -> live San Antonio MAC.BID scan
  -> scoring + all-in cost math + dedupe
  -> static catalog build
  -> browser smoke test
  -> GitHub Pages
  -> https://xotichaze.github.io/Scraper-Public/
```

The deal-engine workflow also runs automatically at minutes `17` and `47` of every hour. The Pages UI includes a **Run fresh scan** link for cases where you want a new snapshot immediately before bidding.

> GitHub Pages must be enabled once under **Settings -> Pages -> Source: GitHub Actions**. The workflow is already wired to publish the tested site after that setting is enabled.

## Authority and privacy boundary

This repository is **public compute**, not a declaration that workload inputs, session material, or results are public.

Default rules:

- Public targets and public, non-sensitive results may run directly.
- Never print or persist cookies, authorization headers, browser storage, access tokens, account identifiers, or other session material.
- Any future non-public input must use a run-bound encrypted capsule pattern before it reaches public compute.
- Private or sensitive outputs must be returned only as encrypted envelopes or deterministic sanitized receipts.
- Public workflows have execution authority only. They are not authoritative storage for private project state.
- Workflows should use the minimum GitHub token permissions required.

The encrypted transport pattern is modeled after the proven Foundry/research-compute pattern: one-run X25519 recipient keys generated inside the runner, run-bound authenticated ciphertext, fixed consumers, sanitized receipts, and deletion of transient private material after execution.

`XoticHaze/Scraper` is the separate **private** repository reserved for authenticated/account-state work. The public deal engine does not depend on it.

The current starred Watchlist in the Pages app is browser-local `localStorage`; it is not uploaded or published. Public research annotations about public auction lots are deliberately public. See `docs/PRIVACY_BOUNDARY.md` for the exact split.

### Encrypted private workloads on public compute

A real live Actions run has already proved the manual round trip:

```text
private workload
  -> run-bound encrypted capsule
  -> public GitHub Actions compute
  -> fixed private execution contract
  -> encrypted stdout/results
  -> private-side decryption
```

The unattended producer is implemented as a cron-only Cloudflare Worker. Before releasing any private workload it independently verifies GitHub workflow-run metadata and requires the exact SHA-pinned reusable private-compute runtime recorded by the private authority. Normal UI/application commits therefore cannot silently replace the code that receives private plaintext.

One-time trusted-producer setup is documented at:

`docs/PRIVATE_PRODUCER_SETUP.md`

The remaining live acceptance gate is deployment of that Worker with a narrowly scoped GitHub App and Cloudflare deployment token, followed by an unattended `producer-selftest-v1` round trip.

## MAC.BID deal engine

The primary workload is a category-agnostic local bargain engine rather than a lock-specific scraper.

Default market scope:

- San Antonio only

Default condition policy:

- prefer `LIKE NEW`
- allow `OPEN BOX`
- exclude `DAMAGED`
- exclude pallets unless explicitly enabled
- suppress listings below a configurable stated-retail floor

The engine bootstraps MAC.BID's public Typesense search contract from the San Antonio location page, keeps only the local open-inventory query, scans the complete eligible San Antonio catalog, scores lots, collapses duplicate products, and builds a bounded market-verification queue.

### Exact ending-soonest authority

A browser probe of MAC.BID's own `Ending Soonest` control confirmed the native search contract:

```text
filter: expected_closing_utc > current epoch
sort:   expected_closing_utc:asc,ranking_weight:desc
```

The deal engine uses that exact public epoch field rather than inventing a time from MAC.BID's date-only `expected_close_date`. It rechecks the epoch at final ranking so lots that expire during a scan are not surfaced as active.

### Primary views

- `ending_soon` — exact MAC.BID closing timestamp ascending
- `best_value` — deterministic discovery score from condition, current all-in cost estimate, stated-retail spread, bidder competition, and urgency
- `low_competition` — fewest bidders/bids first, using value as a tiebreaker
- `verification_queue` — unique high-ranked products that still require exact-model and real-market-price validation before a bid recommendation

Repeated copies of the same product are grouped so one product cannot flood the surface while alternative active lots remain available for comparison.

### Cost model

Current deterministic cost math uses:

- current hammer bid
- MAC.BID 15% buyer premium
- $3 lot fee
- configurable estimated San Antonio sales tax, currently 8.25%

The UI keeps the pre-tax subtotal visible for auditability but treats **estimated all-in total** as the primary spend number. `Lowest Cost`, the max-cost filter, stated-retail discount/savings, and provisional ceiling math are tax-aware.

The tax basis remains explicitly labeled an estimate until it is reconciled against an actual MAC.BID invoice/receipt. The configured assumption currently applies the 8.25% estimate to hammer + buyer premium + lot fee.

Provisional max bids remain intentionally conservative and are based only on MAC.BID's stated retail until exact product/model and external market-price verification are available.

Configuration lives in `config/macbid_deal_engine.json`.

The first-stage engine is inventory-first. Direct searches, brands, categories, and future personal-interest overlays are applied over the same local inventory snapshot instead of spawning one scraper per keyword.

## MAC.BID Hunt UI

Every successful deal-engine run builds an image-first static browser from the current San Antonio snapshot.

Current UI capabilities:

- real MAC.BID product images loaded lazily from the public catalog
- free-text product/brand/category/UPC/model search
- semantic hunt profiles for projectors, curved/large gaming monitors, speakers, solar, HAOS cameras/locks, rugs, tools, Samsung tablets, Apple devices, tech, and preliminary resale
- category and condition filters
- close-within and max-estimated-all-in filters
- zero-bidder hunting
- `Ending Soon`, `Best Value`, `Low Competition`, and `Lowest Cost` ordering
- exact live countdowns from `expected_closing_utc`
- current bid, 15% premium, $3 lot fee, estimated pre-tax subtotal, estimated sales tax, estimated all-in total, stated retail, discount, savings, and provisional max bid
- duplicate-lot alternatives with direct MAC.BID links
- browser-local watchlist
- separate Finds & Watchlists follow-along page with current research notes/source links
- direct repo and fresh-scan controls
- a reserved market-verification panel for verified new price, realistic open-box value, verdict, verified discount, and final max bid

The workflow also uploads a `macbid-hunt-ui` artifact containing a self-contained fallback site. Download it, unzip it, and open `index.html`; `catalog.js` is embedded specifically so the UI works directly from disk without a local server.

## Account layer

Authenticated saved/watchlisted lots, search history, bids/wins, or other personal MAC.BID state belong in private `XoticHaze/Scraper` and should feed only the minimum needed preference/state signal into public compute through the encrypted transport boundary.

A public Pages frontend must never contain a GitHub PAT or MAC.BID account credential merely to trigger compute. Authenticated actions stay on trusted infrastructure; the public frontend can deep-link into GitHub's authenticated workflow UI until the generic action bridge is deployed.

## Discovery probes

Earlier probe workflows remain as diagnostic tools for MAC.BID network/search changes. They capture only sanitized public metadata and do not capture request headers, cookies, browser storage, or authentication state.
