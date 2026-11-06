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

These are **registered prospective sources**, not integrated collectors. Avoid duplicate agency lots, require total landed cost (premium, shipping, tax, travel, removal), and fail closed where collection rights or item condition are unknown.

## Provider documentation
- eBay Browse: https://developer.ebay.com/develop/api/buy/browse_api
- eBay production access policy: https://developer.ebay.com/api-docs/buy/buy-requirements.html
- Best Buy APIs: https://developer.bestbuy.com/apis
- Best Buy API reference: https://bestbuyapis.github.io/api-documentation/
- GSA official guidance: https://www.gsa.gov/buy-through-us/government-property-for-sale-or-lease/office-of-personal-property-management/for-citizens-seeking-surplus-property
