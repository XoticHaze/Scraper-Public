from __future__ import annotations

import json
from playwright.sync_api import Request, sync_playwright

URL = "https://www.mac.bid/search"


def safe_searches(request: Request):
    if "typesense.net/multi_search" not in request.url:
        return None
    try:
        payload = request.post_data_json
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    out = []
    for search in payload.get("searches", []):
        if not isinstance(search, dict):
            continue
        out.append(
            {
                "q": search.get("q"),
                "filter_by": search.get("filter_by"),
                "sort_by": search.get("sort_by"),
                "page": search.get("page"),
                "per_page": search.get("per_page"),
            }
        )
    return out


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1400}, locale="en-US")
        seen = set()

        def on_request(request: Request):
            searches = safe_searches(request)
            if searches is None:
                return
            rendered = json.dumps(searches, sort_keys=True)
            if rendered not in seen:
                seen.add(rendered)
                print("SORT_REQUEST " + rendered)

        page.on("request", on_request)
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5_000)

        controls = page.locator("button, [role='button'], label").evaluate_all(
            """els => els.map((e,i) => ({i, text:(e.innerText || e.textContent || '').trim().slice(0,200), aria:e.getAttribute('aria-label') || ''}))
                .filter(x => /sort|ending|soon|close|price/i.test(x.text + ' ' + x.aria)).slice(0,80)"""
        )
        print("SORT_CONTROLS " + json.dumps(controls, sort_keys=True))

        changed = False

        # The current MAC.BID UI renders the sort choices as custom controls rather
        # than a native <select>. Try the visible choice directly first.
        try:
            choice = page.get_by_text("Ending Soonest", exact=True).first
            choice.click(timeout=5_000)
            page.wait_for_timeout(4_000)
            print("SORT_CLICKED_DIRECT Ending Soonest")
            changed = True
        except Exception as direct_error:
            print(f"SORT_DIRECT_MISS={type(direct_error).__name__}")

        if not changed:
            # Open the custom sort menu using literal selectors only. Avoid callable
            # role-name selectors because Playwright Python expects str/regex here.
            opened = False
            for label in ("Sort: Best Match", "Sort"):
                try:
                    trigger = page.get_by_text(label, exact=True).first
                    trigger.click(timeout=4_000)
                    page.wait_for_timeout(700)
                    print(f"SORT_TRIGGER_CLICKED {label!r}")
                    opened = True
                    break
                except Exception:
                    continue

            if opened:
                try:
                    choice = page.get_by_text("Ending Soonest", exact=True).first
                    choice.click(timeout=5_000)
                    page.wait_for_timeout(4_000)
                    print("SORT_CLICKED_AFTER_OPEN Ending Soonest")
                    changed = True
                except Exception as choice_error:
                    print(f"SORT_CHOICE_MISS={type(choice_error).__name__}")

        print(f"SORT_CHANGED={changed}")
        browser.close()
    return 0 if changed else 2


if __name__ == "__main__":
    raise SystemExit(main())
