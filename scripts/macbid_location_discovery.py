from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

LOCATION_URL = "https://www.mac.bid/locations/san-antonio"
SEARCH_URL = "https://www.mac.bid/search?q=Kwikset"
OUTPUT = Path("results/macbid-location-discovery.json")

SENSITIVE_QUERY_RE = re.compile(
    r"(?:token|auth|authorization|cookie|session|secret|key|signature|credential|jwt)",
    re.IGNORECASE,
)
LOCATION_RE = re.compile(r"san\s*antonio|schertz", re.IGNORECASE)
INTEREST_RE = re.compile(r"location|market|warehouse|search|auction|lot|product|san.?antonio|schertz", re.IGNORECASE)


def sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    safe_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        safe_query.append((key, "REDACTED" if SENSITIVE_QUERY_RE.search(key) else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def compact(value: str, limit: int = 900) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def safe_attrs(attrs: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in attrs.items():
        k = key.lower()
        if SENSITIVE_QUERY_RE.search(k):
            continue
        if k in {"href", "src"}:
            out[key] = sanitize_url(value)
        elif k.startswith("data-") or k in {"id", "name", "role", "aria-label", "value", "class"}:
            out[key] = compact(value, 300)
    return out


def elements_near(page, pattern: str) -> list[dict]:
    rows = page.locator("a,button,label,input,[role='button'],[role='checkbox']").evaluate_all(
        """(els, pattern) => {
          const rx = new RegExp(pattern, 'i');
          return els.map(el => {
            const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
            const parent = el.parentElement ? (el.parentElement.innerText || '').trim() : '';
            const attrs = {};
            for (const a of el.attributes || []) attrs[a.name] = a.value;
            return {tag: el.tagName.toLowerCase(), text, parent, attrs};
          }).filter(x => rx.test(x.text) || rx.test(x.parent)).slice(0, 120);
        }""",
        pattern,
    )
    out = []
    for row in rows:
        out.append(
            {
                "tag": row.get("tag", ""),
                "text": compact(row.get("text", ""), 350),
                "parent": compact(row.get("parent", ""), 600),
                "attrs": safe_attrs(row.get("attrs", {})),
            }
        )
    return out


def matching_links(page) -> list[dict]:
    rows = page.locator("a[href]").evaluate_all(
        """els => els.map(a => ({
          href: a.href || '',
          text: (a.innerText || '').trim(),
          parent: a.parentElement ? (a.parentElement.innerText || '').trim() : ''
        }))"""
    )
    out = []
    seen = set()
    for row in rows:
        href = sanitize_url(str(row.get("href", "")))
        text = compact(str(row.get("text", "")), 350)
        parent = compact(str(row.get("parent", "")), 600)
        joined = f"{href} {text} {parent}"
        if not INTEREST_RE.search(joined) or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "text": text, "parent": parent})
    return out[:200]


def scan_public_object(value, path: str = "$", depth: int = 0, found=None):
    if found is None:
        found = []
    if len(found) >= 100 or depth > 8:
        return found
    if isinstance(value, dict):
        for key, child in value.items():
            scan_public_object(child, f"{path}.{key}", depth + 1, found)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:200]):
            scan_public_object(child, f"{path}[{idx}]", depth + 1, found)
    elif isinstance(value, (str, int, float, bool)):
        text = str(value)
        if LOCATION_RE.search(text) or (INTEREST_RE.search(path) and len(text) <= 300):
            found.append({"path": path, "value": compact(text, 500)})
    return found


def lot_links(page) -> list[dict]:
    rows = page.locator("a[href]").evaluate_all(
        """els => els.map(a => {
          let node = a;
          for (let i=0; i<4 && node && node.parentElement; i++) node = node.parentElement;
          return {href: a.href || '', text: (a.innerText || '').trim(), context: node ? (node.innerText || '').trim() : ''};
        })"""
    )
    out = []
    seen = set()
    for row in rows:
        href = sanitize_url(str(row.get("href", "")))
        path = urlsplit(href).path.lower()
        if not ("/auction/" in path or "/turbo-clock-auctions/" in path or "/product" in path):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(
            {
                "url": href,
                "text": compact(str(row.get("text", "")), 350),
                "context": compact(str(row.get("context", "")), 900),
            }
        )
    return out[:100]


def run() -> int:
    report = {
        "schema": "macbid-location-discovery-v1",
        "privacy": {
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "request_bodies_captured": False,
            "raw_page_html_captured": False,
        },
        "location_page": {},
        "kwikset_search": {},
        "network": [],
    }
    seen_net = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1300})
        page = context.new_page()

        def on_response(response):
            try:
                req = response.request
                if req.resource_type not in {"xhr", "fetch", "document"}:
                    return
                clean = sanitize_url(response.url)
                key = (req.method, clean, response.status)
                if key in seen_net:
                    return
                seen_net.add(key)
                node = {
                    "method": req.method,
                    "type": req.resource_type,
                    "status": response.status,
                    "host": urlsplit(clean).hostname or "",
                    "url": clean,
                    "content_type": (response.header_value("content-type") or "").split(";", 1)[0],
                }
                report["network"].append(node)
                print("LOCATION_NET " + json.dumps(node, sort_keys=True))
            except Exception as exc:
                print(f"LOCATION_NET_ERROR {type(exc).__name__}")

        page.on("response", on_response)

        nav = page.goto(LOCATION_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(6_000)
        loc = report["location_page"]
        loc["status"] = nav.status if nav else None
        loc["url"] = sanitize_url(page.url)
        loc["title"] = page.title()
        loc["elements"] = elements_near(page, r"san\s*antonio|schertz|browse|auction")
        loc["links"] = matching_links(page)
        try:
            loc["next_data_matches"] = scan_public_object(page.evaluate("() => window.__NEXT_DATA__ || null"))
        except Exception as exc:
            loc["next_data_matches"] = [{"error": type(exc).__name__}]
        print(f"LOCATION_PAGE status={loc['status']} elements={len(loc['elements'])} links={len(loc['links'])}")
        for row in loc["elements"][:40]:
            print("LOCATION_ELEMENT " + json.dumps(row, sort_keys=True))
        for row in loc["next_data_matches"][:80]:
            print("LOCATION_NEXT_MATCH " + json.dumps(row, sort_keys=True))

        nav = page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(7_000)
        search = report["kwikset_search"]
        search["status"] = nav.status if nav else None
        search["url"] = sanitize_url(page.url)
        search["title"] = page.title()
        search["location_elements"] = elements_near(page, r"san\s*antonio|schertz")
        search["lot_links"] = lot_links(page)
        print(f"KWIKSET_QUERY status={search['status']} lots={len(search['lot_links'])} location_elements={len(search['location_elements'])}")
        for row in search["location_elements"][:40]:
            print("KWIKSET_LOCATION_ELEMENT " + json.dumps(row, sort_keys=True))
        for row in search["lot_links"][:40]:
            print("KWIKSET_LOT " + json.dumps(row, sort_keys=True))

        context.close()
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("LOCATION_DISCOVERY_REPORT=" + str(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
