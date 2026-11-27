"""Read back the exact deployed public catalog and an independently priced card."""
import argparse
import time
from playwright.sync_api import sync_playwright

URL = "https://xotichaze.github.io/Scraper-Public/"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--epoch", type=int, required=True)
    args = p.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        catalog = None
        for attempt in range(6):
            try:
                response = context.request.get(f"{URL}catalog.json?readback={args.epoch}-{attempt}",
                    headers={"Cache-Control": "no-cache"}, timeout=20000)
                if response.ok:
                    data = response.json()
                    if data.get("generated_epoch_utc") == args.epoch:
                        catalog = data
                        break
            except Exception:
                pass
            time.sleep(5)
        assert catalog is not None, "Exact deployed generation not visible"
        products = catalog.get("products") or []
        assert products and catalog["lot_count"] > 0
        assert catalog["product_count"] == len(products)
        assert catalog["market_value_count"] == sum(p.get("market_price_status") == "verified_external" for p in products)
        candidates = [p for p in products if p.get("market_price_status") == "verified_external"
                      and p.get("market_value_authoritative") and p.get("upc")
                      and any(l.get("expected_closing_utc", 0) > time.time() + 90 for l in p.get("lots", []))]
        candidates.sort(key=lambda p: "ice-makers" not in (p.get("hunt_ids") or []))
        # No live external price is a legitimate discovery state, not a fabricated card.
        chosen = candidates[0] if candidates else None
        page.goto(f"{URL}?readback={args.epoch}", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector(".card", timeout=30000)
        assert page.evaluate("state.catalog.generated_epoch_utc") == args.epoch, "UI loaded different generation"
        assert "market-verified" in page.locator("#catalog-meta").inner_text()
        assert "legacy unresolved" in page.locator("#catalog-meta").inner_text()
        assert "legacy sold" in page.locator("#catalog-meta").inner_text()
        if chosen:
            page.fill("#search", str(chosen["upc"]))
            card = page.locator(".card").filter(has_text=chosen["name"]).first
            card.wait_for(timeout=15000)
            assert card.get_attribute("data-identity") == chosen["identity"]
            # Chips use CSS uppercase. Assert visible text case-insensitively, not a raw case-sensitive DOM string.
            assert "market verified" in card.inner_text().casefold(), card.inner_text()
            card.locator(".card-open").click()
            page.wait_for_selector("#detail-dialog[open] .verify-box")
            verification = page.locator("#detail-dialog .verify-box").filter(has_text="External market valuation").first
            assert verification.is_visible()
            assert verification.locator("a[href^='https://']").count() > 0
            assert page.locator("#detail-dialog").get_by_text("Historical acquisition evidence", exact=False).first.is_visible()
            assert page.locator("#detail-dialog").get_by_text("Recovered legacy / unresolved",exact=True).is_visible()
            assert page.locator("#detail-dialog").get_by_text("Protected purchase alternatives",exact=True).is_visible()
            selected_lot = next((l for l in chosen.get("lots",[]) if l.get("observed_bid_history")), None)
            if selected_lot and all(l.get("observed_bid_history") for l in chosen.get("lots",[])):
                assert page.locator("#detail-dialog").get_by_text("Observed bid trajectory",exact=True).is_visible()
                print("SERVED_BID_TRAJECTORY=PASS")
            quote = page.locator("#local-protected-quote")
            assert quote.is_visible()
            page.fill("#quote-total", "120")
            page.fill("#quote-extra", "10")
            page.fill("#quote-returns", "30")
            assert "No bid ceiling yet" in page.locator("#quote-result").inner_text()
            page.check("#quote-exact")
            result = page.locator("#quote-result").inner_text()
            assert "$59.99" in result, result
            assert "Scenario maximum hammer" in result
            assert "independent valuation" in result
            print("SERVED_LOCAL_PROTECTED_QUOTE=PASS")
            print(f"SERVED_MARKET_CARD=PASS identity={chosen['identity']} ice_pilot={'ice-makers' in (chosen.get('hunt_ids') or [])}")
        else:
            print("SERVED_MARKET_CARD=NO_CURRENT_VERIFIED_PRODUCT")
        page.goto(f"{URL}finds.html?readback={args.epoch}",wait_until="domcontentloaded",timeout=30000)
        page.wait_for_selector("#ice-makers",timeout=30000)
        for profile in catalog.get("hunt_profiles",[]):
            assert page.locator("[id="+repr(profile["id"])+"]").count()==1, profile["id"]
        assert "legacy" in page.locator("#ice-makers .finds-section-head").inner_text()
        print("SERVED_ALL_HUNT_HISTORY=PASS profiles="+str(len(catalog["hunt_profiles"])))
        evidence = page.locator("#ice-model-evidence")
        assert evidence.is_visible()
        assert "not current inventory" in evidence.inner_text()
        assert "Whynter IMC-491DC" in evidence.inner_text()
        assert "Avalon A-ICE2" in evidence.inner_text()
        assert evidence.locator("a[href^=\'https://\']").count() >= 3
        print("SERVED_ICE_MODEL_EVIDENCE=PASS")
        print(f"SERVED_CATALOG=PASS epoch={args.epoch} products={len(products)} lots={catalog['lot_count']} verified={catalog['market_value_count']}")

        # Fresh mobile Chromium acceptance of the real served generation.
        # The clipboard shim observes the app's writeText calls; this does NOT
        # claim native iOS/Safari clipboard permission or device acceptance.
        mobile = browser.new_context(viewport={"width": 390, "height": 844},
                                     is_mobile=True, has_touch=True, device_scale_factor=3)
        mobile.add_init_script("""
window.__copyLog = [];
Object.defineProperty(navigator, 'clipboard', {
  configurable: true,
  value: {writeText: async (text) => window.__copyLog.push(String(text))}
});
""")
        mobile_page = mobile.new_page()
        mobile_page.goto(f"{URL}?mobile_readback={args.epoch}", wait_until="domcontentloaded", timeout=30000)
        mobile_page.wait_for_selector(".card-open", timeout=30000)
        assert mobile_page.evaluate("state.catalog.generated_epoch_utc") == args.epoch, "Mobile UI loaded different generation"
        first = mobile_page.locator(".card").first
        identity = first.get_attribute("data-identity")
        selected = next((item for item in products if item.get("identity") == identity), None)
        assert selected is not None, "Mobile card does not bind a served product"
        first.locator(".card-open").click()
        copy_search = mobile_page.locator("#detail-dialog[open] #copy-search")
        assert copy_search.is_visible(), "Mobile Copy search action not visible"
        assert mobile_page.locator("#copy-mac-id").is_visible()
        assert mobile_page.locator("#copy-lot-ref").is_visible()
        copy_search.click()
        copied = mobile_page.evaluate("window.__copyLog[window.__copyLog.length - 1]")
        brand, model = str(selected.get("brand") or "").strip(), str(selected.get("model") or "").strip()
        expected = (brand + " " + model) if brand and model else str(selected.get("name") or "").strip()
        assert copied == expected and expected, f"Mobile copied search text mismatch: {copied!r} != {expected!r}"
        # Existing watchlist is browser-local, no native MAC.BID account action.
        mobile_page.locator("#detail-watch").click()
        mobile_page.goto(f"{URL}finds.html?mobile_readback={args.epoch}",
                         wait_until="domcontentloaded", timeout=30000)
        finds_copy = mobile_page.locator("#my-watchlist .copy-search").first
        finds_copy.wait_for(timeout=30000)
        finds_copy.click()
        assert mobile_page.evaluate("window.__copyLog[window.__copyLog.length - 1]") == expected
        print("SERVED_MOBILE_CHROMIUM_COPY_SEARCH=PASS viewport=390x844 cards=Hunt+Finds")
        mobile.close()
        browser.close()

if __name__ == "__main__":
    main()
