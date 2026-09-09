from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Page, sync_playwright

TARGET = "https://www.mac.bid/search"
TERMS = ("Kwikset", "Schlage", "Aqara", "Yale", "Chamberlain", "Z-Wave", "Matter")
OUTPUT = Path("results/macbid-search-discovery.json")

SENSITIVE_QUERY_RE = re.compile(
    r"(?:token|auth|authorization|cookie|session|secret|key|signature|credential|jwt)",
    re.IGNORECASE,
)
LOT_PATH_RE = re.compile(r"/(?:auction|turbo-clock-auctions|products?)/", re.IGNORECASE)


def sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    safe_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        safe_query.append((key, "REDACTED" if SENSITIVE_QUERY_RE.search(key) else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def compact(text: str, limit: int = 700) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def json_shape(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        keys = sorted(str(k) for k in value.keys())[:60]
        out: dict[str, Any] = {"type": "object", "keys": keys}
        for candidate in ("props", "pageProps", "data", "items", "results", "products", "lots", "auctions"):
            if candidate in value:
                out[candidate] = json_shape(value[candidate], depth + 1)
        return out
    if isinstance(value, list):
        out: dict[str, Any] = {"type": "array", "length": len(value)}
        if value:
            out["first"] = json_shape(value[0], depth + 1)
        return out
    return {"type": type(value).__name__}


def collect_cards(page: Page) -> list[dict[str, str]]:
    rows = page.locator("a[href]").evaluate_all(
        """els => els.map(a => {
          let node = a;
          for (let i = 0; i < 4 && node && node.parentElement; i++) node = node.parentElement;
          return {
            href: a.href || '',
            text: (a.innerText || '').slice(0, 300),
            context: ((node && node.innerText) || '').slice(0, 1200)
          };
        })"""
    )
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        href = sanitize_url(str(row.get("href", "")))
        if not href or not LOT_PATH_RE.search(urlsplit(href).path) or href in seen:
            continue
        seen.add(href)
        found.append(
            {
                "url": href,
                "text": compact(str(row.get("text", "")), 300),
                "context": compact(str(row.get("context", "")), 700),
            }
        )
        if len(found) >= 120:
            break
    return found


def collect_checkbox_context(page: Page) -> list[dict[str, Any]]:
    rows = page.locator('input[type="checkbox"]').evaluate_all(
        """els => els.slice(0, 120).map(e => ({
          checked: !!e.checked,
          value: e.value || '',
          id: e.id || '',
          parent_text: ((e.parentElement && e.parentElement.innerText) || '').slice(0, 300),
          grandparent_text: ((e.parentElement && e.parentElement.parentElement && e.parentElement.parentElement.innerText) || '').slice(0, 500)
        }))"""
    )
    out = []
    for row in rows:
        text = compact(str(row.get("parent_text") or row.get("grandparent_text") or ""), 300)
        if text:
            out.append(
                {
                    "checked": bool(row.get("checked")),
                    "value": compact(str(row.get("value", "")), 120),
                    "id": compact(str(row.get("id", "")), 120),
                    "text": text,
                }
            )
    return out[:80]


def run() -> int:
    report: dict[str, Any] = {
        "schema": "macbid-search-discovery-v1",
        "privacy": {
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "request_bodies_captured": False,
        },
        "network": [],
        "next_data_shape": None,
        "checkboxes": [],
        "searches": [],
    }
    seen_network: set[tuple[str, str, str]] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1300})
        page = context.new_page()

        def on_response(response) -> None:
            try:
                request = response.request
                if request.resource_type not in {"xhr", "fetch", "document"}:
                    return
                clean = sanitize_url(response.url)
                host = (urlsplit(clean).hostname or "").lower()
                key = (request.method, clean, str(response.status))
                if key in seen_network:
                    return
                seen_network.add(key)
                content_type = (response.header_value("content-type") or "").split(";", 1)[0].lower()
                node = {
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "status": response.status,
                    "host": host,
                    "url": clean,
                    "content_type": content_type,
                }
                if (content_type == "application/json" or content_type.endswith("+json")) and len(report["network"]) < 200:
                    try:
                        node["json_shape"] = json_shape(response.json())
                    except Exception:
                        node["json_shape"] = {"type": "unreadable_json"}
                report["network"].append(node)
                if len(report["network"]) <= 250:
                    print(f"DISCOVERY_NET {request.resource_type} {response.status} {clean}")
            except Exception as exc:  # pragma: no cover
                print(f"DISCOVERY_CALLBACK_ERROR {type(exc).__name__}")

        page.on("response", on_response)
        nav = page.goto(TARGET, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)
        print(f"DISCOVERY_PAGE status={nav.status if nav else None} url={page.url} title={page.title()!r}")

        try:
            next_data = page.evaluate("() => window.__NEXT_DATA__ || null")
            report["next_data_shape"] = json_shape(next_data)
            print("DISCOVERY_NEXT_DATA " + json.dumps(report["next_data_shape"], sort_keys=True))
        except Exception as exc:
            report["next_data_shape"] = {"error": type(exc).__name__}

        report["checkboxes"] = collect_checkbox_context(page)
        for node in report["checkboxes"]:
            lowered = node["text"].lower()
            if "san antonio" in lowered or "schertz" in lowered:
                print("DISCOVERY_LOCATION_FILTER " + json.dumps(node, sort_keys=True))

        search = page.locator('input[type="search"]').first
        for term in TERMS:
            node: dict[str, Any] = {"term": term}
            try:
                search = page.locator('input[type="search"]').first
                search.fill(term)
                search.press("Enter")
                page.wait_for_timeout(6_000)
                node["url"] = sanitize_url(page.url)
                node["title"] = page.title()
                node["cards"] = collect_cards(page)
                node["body_excerpt"] = compact(page.locator("body").inner_text(), 1000)
                print(f"DISCOVERY_SEARCH term={term!r} url={node['url']} cards={len(node['cards'])}")
                for card in node["cards"][:20]:
                    print("DISCOVERY_CARD " + json.dumps(card, sort_keys=True))
            except Exception as exc:
                node["error"] = f"{type(exc).__name__}: {exc}"
                print(f"DISCOVERY_SEARCH_ERROR term={term!r} {node['error']}")
            report["searches"].append(node)

        context.close()
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("DISCOVERY_REPORT=" + str(OUTPUT))
    print("DISCOVERY_NETWORK_COUNT=" + str(len(report["network"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
