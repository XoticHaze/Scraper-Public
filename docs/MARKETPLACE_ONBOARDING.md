# Marketplace expansion: eBay / Best Buy opt-in onboarding (2026-11-06)

## What is actually implemented
- `deal_engine/marketplace/normalizers.py` maps **individual** eBay Browse item responses, Best Buy Products API responses, and Best Buy Buying Options open-box responses into a common offer representation.
- `deal_engine/marketplace/probes.py` provides narrowly scoped, **read-only, manual item/SKU probes** (no discovery, scheduling, purchases, bids, credentials in the repo, or public Pages publishing).
- `config/marketplace_sources.json` registers eBay, Best Buy, GSA Auctions, GovDeals, Public Surplus, San Antonio Surplus, and Texas State Surplus, with Walmart and H-E-B remaining access-gated.
- `tests/test_marketplace_onboarding.py` validates model contradictions, authenticity unknowns, URL/token safety, open-box normalization, and fail-closed missing credentials.

**No scheduled scans or product watches are enabled.** Neither external API access nor a live marketplace listing has been verified by this PR. Never call an illustrative fixture a live price. 

## Manual operator probes (authorized runtime only)
Register and receive developer access directly from the provider; **do not commit keys**. These commands require the associated environment variables to be supplied by an authorized secret store at execution time.

```bash
# With EBAY_APP_TOKEN set to an authorized app OAuth token:
python -m deal_engine.marketplace.probes --ebay-item-id 227505526667

# With BESTBUY_API_KEY configured by the runtime:
python -m deal_engine.marketplace.probes --bestbuy-sku 1234567
python -m deal_engine.marketplace.probes --bestbuy-sku 1234567 --bestbuy-open-box
```

Do not use those sample IDs as source-verified current listings. An operator should select a real ID/SKU when executing. API failures do not trigger a fallback scraper or mark a listing verified.

## Authority boundaries
- `XoticHaze/Scraper-Public`: source-agnostic offer contract, deterministic risk warnings, fixture tests, and permissible public projection.
- `XoticHaze/Scraper`: private account/session information, keys, saved preferences and private results. Public encrypted computation uses admitted scoped routes; **private GitHub Actions compute is prohibited**.
- No credentials, tokens, session storage, precise address, or private preferences go into GitHub Pages, the public repository, logs, or sample fixtures.
- Best Buy API content and links have provider restrictions on caching/reuse. A probe prints transient observations and does **not** append them into a long-lived published price-history file.
- The adapter records `live_verified=false` because normalization is not a live checkout, identity or seller authentication. Future publisher must apply independent freshness, permission, and data-rights checks.
- eBay ratings do **not** prove authenticity; seller trust and model evidence are evaluated separately, and no normalized offer may get an automatic BUY verdict.
- Price is **not** landed cost: tax, shipping, buyer premiums, pickup and other costs remain unknown until the relevant venue details are obtained.

## Recommended next activation milestones
1. Verify operator eBay developer program keys and production eligibility for the required Browse operations. Query only public item IDs initially.
2. Verify Best Buy developer API key and entitlement for Products and Buying Options. Confirm returns, condition, and location-dependent offer behavior against source output.
3. Add permitted live source jobs on the approved execution route, with source-specific freshness and rate limits; do not couple failure to the MAC.BID scheduled publication.
4. Build the cross-retailer retail UI only after real data exists, with image, source, seller, all-in cost, and observed-at fields. Keep grocery separate.

## Auction source shortlist
- GSA Auctions (https://gsaauctions.gov/): federal surplus, vehicles, lab, office and specialized hardware; as-is property and shipping/pickup costs.
- GovDeals (https://www.govdeals.com/): municipal, school and agency surplus, often local pickup.
- Public Surplus (https://www.publicsurplus.com/): government agency surplus; Texas Facilities Commission points here and to GovDeals.
- City of San Antonio surplus (https://webapp1.sanantonio.gov/surplus/): direct municipal bid platform; **distinct from GovDeals**.
- Texas Facilities Commission (https://web.tfc.texas.gov/public/state-surplus-store): agency/origin index, not necessarily a separate listing when it forwards to GovDeals/Public Surplus.
- GSA Fleet (https://www.gsafleet.gov/): government-owned vehicles; feed into the **existing Vehicle Hunt** rather than duplicating VIN and price-history code.
- ShopGoodwill (https://shopgoodwill.com/): a useful discovery source for instruments, music gear, tech and electronics, but seller-specific shipping/handling and pickup terms can erase savings.

These are **registered prospective sources**, not integrated collectors. Avoid duplicate agency lots, require total landed cost (premium, shipping, tax, travel, removal), and fail closed where collection rights or item condition are unknown.

## Provider documentation
- eBay Browse: https://developer.ebay.com/develop/api/buy/browse_api
- eBay production access policy: https://developer.ebay.com/api-docs/buy/buy-requirements.html
- Best Buy APIs: https://developer.bestbuy.com/apis
- Best Buy API reference: https://bestbuyapis.github.io/api-documentation/
- GSA official guidance: https://www.gsa.gov/buy-through-us/government-property-for-sale-or-lease/office-of-personal-property-management/for-citizens-seeking-surplus-property

## GSA and marketplace source hub (2026-11-06)

The official GSA Auctions GET API was tested against the source's documented `DEMO_KEY`; the live result returned **1,125 nationwide records** with a `Results` wrapper and camelCase auction fields. The API schema was corrected against these actual response keys; a public workflow completed successfully without credentials.

- `deal_engine/marketplace/gsa.py`: validates, normalizes, deduplicates real sale/lot identities and preserves date-only closing precision.
- `scripts/gsa_public_scan.py --demo-probe`: explicit one-off bounded public API test, no catalog publication.
- `scripts/gsa_public_scan.py --state TX`: authorized runtime needs `GSA_API_KEY`; publishes `results/gsa-auctions.json` only after validated data.
- `ui/marketplaces.html`: multi-source directory; verified fresh GSA results appear only if the runtime provides and validates a snapshot within 24 hours.
- No `DEMO_KEY` in schedules, no unauthorized crawling, and no claims of price history, all-in cost, accurate close time or max bid from GSA's date-only response.
- GovDeals' terms ban automated crawlers/data mining; Public Surplus forbids automated monitoring without prior express written permission; ShopGoodwill requires consent for automated extraction. Their onboarding is **official discovery links only**.
- The City of San Antonio's surplus page is public and independently useful for local pickup, but its site contract is not validated as an automated source. The hub links directly to it.
- eBay and Best Buy listing probes remain ready when per-operator developer credentials are provided. Never borrow, embed or publish another application's API key.

Official references: https://gsa.github.io/auctions_api/ , https://gsa.github.io/auctions_api/fields ,
https://prod-seo.govdeals.com/content/site-terms ,
https://m.publicsurplus.com/sms/login/plainTermsAndConditions ,
https://shopgoodwill.com/about/terms-of-use

## GSA authorized publication and usable cross-source shortlist (2026-11-07)

The **public** MAC.BID workflow retains its existing schedule, independent source contracts and Pages deployment. A new optional source step checks for an independently configured `GSA_API_KEY` GitHub Actions secret at runtime; when present, it runs `python -m scripts.gsa_public_scan --state TX` before staging the site. When absent, it logs `GSA_SOURCE=KEY_NOT_CONFIGURED` and continues the MAC.BID job without inventing GSA inventory. Network/API errors in this secondary step also cannot block MAC.BID. This path **never** schedules the shared `DEMO_KEY`.

The Pages builder now requires an internally consistent, dated GSA snapshot: official source identity and allowlisted links, matching count and unique lot IDs, active status, TX state consistency, date-only close precision, and explicitly unknown all-in costs and bid ceilings. Snapshots older than 24 hours or with future timestamps are rejected. The browser independently rejects stale snapshots too.

The marketplace UI now supports Texas-focused GSA searching, keyword hunt focus (UPS/power, home automation/cameras, rack/networking, instruments, vehicles, tech), San Antonio-first priority, closing-date sorting, lowest observed high-bid sorting and a maximum observed bid filter. These are **discovery filters**, not authenticity checks or bid recommendations. GSA's date-only close fields remain date-only; an observed high bid never becomes a verified total cost or a maximum bid.

A new **browser-local manual shortlist** accepts official HTTPS item URLs from registered sources including eBay, Best Buy, GSA, GovDeals, Public Surplus, ShopGoodwill and San Antonio Surplus, plus user-entered titles, notes and optional asking-price/bid observations. Re-saving the same link creates another manual price observation. Those observations are not a verified market price history. It does **not** scrape, monitor, contact or bid on third-party sites, and it does **not** upload the shortlist to the repository. Unapproved sources remain discovery-only.

Activation when the user obtains a personal GSA key:
1. Add `GSA_API_KEY` as an Actions secret in **XoticHaze/Scraper-Public** only through an approved operator/secret-handling route. Do not paste credentials into issues, PRs, chat, code or workflow arguments. Confirm this public repo's main-branch workflow is the approved consumer before granting access.
2. Allow the next existing public MAC.BID publication to execute, or dispatch its existing manual refresh. The GSA step outputs only status/count, never the secret.
3. Verify `UI_GSA_VERIFIED_AUCTIONS` during build and a fresh `gsa-auctions.json` in the Pages artifact, then inspect live cards on `marketplaces.html`.
4. If GSA is unavailable or the snapshot fails validation, keep the directory/manual shortlist usable without claiming the feed is live.

The personal GSA key is still an external dependency. An adapter and runtime wiring do not imply it has already been supplied, activated or observed serving new auctions.
