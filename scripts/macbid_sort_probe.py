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

        # Surface select/options without dumping arbitrary page state.
        selects = page.locator("select").evaluate_all(
            """els => els.map((s, i) => ({index:i, value:s.value, options:[...s.options].map(o => ({text:o.textContent.trim(), value:o.value}))}))"""
        )
        print("SORT_SELECTS " + json.dumps(selects, sort_keys=True))

        candidates = page.locator("button, [role='button'], label").evaluate_all(
            """els => els.map((e,i) => ({i, text:(e.innerText || e.textContent || '').trim().slice(0,200), aria:e.getAttribute('aria-label') || ''}))
                .filter(x => /sort|ending|soon|close|price/i.test(x.text + ' ' + x.aria)).slice(0,80)"""
        )
        print("SORT_CONTROLS " + json.dumps(candidates, sort_keys=True))

        # First try a native select option containing Ending/Soonest.
        changed = False
        for idx, select in enumerate(selects):
            for option in select.get("options", []):
                text = str(option.get("text", ""))
                if "ending" in text.lower() or "soonest" in text.lower():
                    page.locator("select").nth(idx).select_option(str(option.get("value", "")))
                    page.wait_for_timeout(4_000)
                    print(f"SORT_SELECTED select={idx} text={text!r} value={option.get('value')!r}")
                    changed = True
                    break
            if changed:
                break

        # Custom dropdown fallback.
        if not changed:
            trigger = page.get_by_role("button", name=lambda name: bool(name and "sort" in name.lower())).first
            try:
                trigger.click(timeout=5_000)
                page.wait_for_timeout(500)
            except Exception:
                pass
            for pattern in ("Ending Soon", "Ending Soonest", "Soonest", "Closing Soon"):
                try:
                    choice = page.get_by_text(pattern, exact=False).first
                    choice.click(timeout=3_000)
                    page.wait_for_timeout(4_000)
                    print(f"SORT_CLICKED pattern={pattern!r}")
                    changed = True
                    break
                except Exception:
                    continue

        print(f"SORT_CHANGED={changed}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
