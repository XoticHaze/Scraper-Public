from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

TARGETS = (
    "https://www.mac.bid/locations/san-antonio",
    "https://www.mac.bid/search",
)
OUTPUT = Path("results/macbid-san-antonio-probe.json")
SENSITIVE_QUERY_RE = re.compile(
    r"(?:token|auth|authorization|cookie|session|secret|key|signature|credential|jwt)",
    re.IGNORECASE,
)
INTERESTING_PATH_RE = re.compile(
    r"(?:api|graphql|search|auction|lot|product|inventory|location|market)",
    re.IGNORECASE,
)


def is_macbid(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "mac.bid" or host.endswith(".mac.bid")


def sanitize_url(url: str) -> str:
    """Retain public query filters while redacting anything session-like."""
    parts = urlsplit(url)
    safe_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        safe_query.append((key, "REDACTED" if SENSITIVE_QUERY_RE.search(key) else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))


def json_shape(value: Any, depth: int = 0) -> Any:
    """Describe JSON structure without dumping arbitrary response bodies."""
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        keys = sorted(str(k) for k in value.keys())[:40]
        result: dict[str, Any] = {"type": "object", "keys": keys}
        for candidate in ("data", "items", "results", "products", "lots", "auctions"):
            if candidate in value:
                result[candidate] = json_shape(value[candidate], depth + 1)
        return result
    if isinstance(value, list):
        result = {"type": "array", "length": len(value)}
        if value:
            result["first"] = json_shape(value[0], depth + 1)
        return result
    return {"type": type(value).__name__}


def add_page_observers(page: Page, report: dict[str, Any]) -> None:
    seen_requests: set[tuple[str, str]] = set()
    seen_responses: set[tuple[str, int]] = set()

    def on_request(request) -> None:
        try:
            if request.resource_type not in {"xhr", "fetch"} or not is_macbid(request.url):
                return
            url = sanitize_url(request.url)
            key = (request.method, url)
            if key in seen_requests:
                return
            seen_requests.add(key)
            report["requests"].append(
                {
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "url": url,
                    "interesting": bool(INTERESTING_PATH_RE.search(urlsplit(url).path)),
                }
            )
            print(f"MACBID_REQUEST {request.method} {url}")
        except Exception as exc:  # pragma: no cover - diagnostic callback
            report["callback_errors"].append(f"request:{type(exc).__name__}")

    def on_response(response: Response) -> None:
        try:
            request = response.request
            if request.resource_type not in {"xhr", "fetch"} or not is_macbid(response.url):
                return
            url = sanitize_url(response.url)
            key = (url, response.status)
            if key in seen_responses:
                return
            seen_responses.add(key)
            content_type = (response.header_value("content-type") or "").split(";", 1)[0].strip().lower()
            node: dict[str, Any] = {
                "status": response.status,
                "url": url,
                "content_type": content_type,
                "interesting": bool(INTERESTING_PATH_RE.search(urlsplit(url).path)),
            }
            if content_type in {"application/json", "application/graphql-response+json"} or content_type.endswith("+json"):
                try:
                    node["json_shape"] = json_shape(response.json())
                except Exception:
                    node["json_shape"] = {"type": "unreadable_json"}
            report["responses"].append(node)
            print(f"MACBID_RESPONSE {response.status} {content_type or '-'} {url}")
            if "json_shape" in node:
                print("MACBID_JSON_SHAPE " + json.dumps(node["json_shape"], sort_keys=True))
        except Exception as exc:  # pragma: no cover - diagnostic callback
            report["callback_errors"].append(f"response:{type(exc).__name__}")

    page.on("request", on_request)
    page.on("response", on_response)


def visit(page: Page, url: str, report: dict[str, Any]) -> None:
    node: dict[str, Any] = {"url": url}
    report["pages"].append(node)
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        node["navigation_status"] = response.status if response else None
        node["title"] = page.title()
        print(f"MACBID_PAGE {node['navigation_status']} {url} title={node['title']!r}")
        page.wait_for_timeout(8_000)

        # Browser performance entries can reveal API calls even if an event callback
        # was attached after an early request. URLs only; never headers or storage.
        resource_urls = page.evaluate(
            """() => performance.getEntriesByType('resource').map(e => e.name)"""
        )
        for raw_url in resource_urls:
            if is_macbid(raw_url):
                clean = sanitize_url(raw_url)
                if INTERESTING_PATH_RE.search(urlsplit(clean).path):
                    report["performance_candidates"].append(clean)

        # Record only harmless DOM metadata that can help locate a public search box.
        inputs = page.locator("input").evaluate_all(
            """els => els.slice(0, 30).map(e => ({
                type: e.type || '', name: e.name || '', placeholder: e.placeholder || '',
                aria_label: e.getAttribute('aria-label') || ''
            }))"""
        )
        node["inputs"] = inputs
    except Exception as exc:
        node["error"] = f"{type(exc).__name__}: {exc}"
        print(f"MACBID_PAGE_ERROR {url} {node['error']}")


def run() -> int:
    report: dict[str, Any] = {
        "schema": "macbid-public-network-probe-v1",
        "privacy": {
            "headers_captured": False,
            "cookies_captured": False,
            "browser_storage_captured": False,
            "raw_response_bodies_captured": False,
        },
        "pages": [],
        "requests": [],
        "responses": [],
        "performance_candidates": [],
        "callback_errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context(
            locale="en-US",
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        add_page_observers(page, report)
        for target in TARGETS:
            visit(page, target, report)
        context.close()
        browser.close()

    # Deterministic dedupe of candidate URLs.
    report["performance_candidates"] = sorted(set(report["performance_candidates"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("MACBID_PROBE_REPORT=" + str(OUTPUT))
    print("MACBID_REQUEST_COUNT=" + str(len(report["requests"])))
    print("MACBID_RESPONSE_COUNT=" + str(len(report["responses"])))
    print("MACBID_PERFORMANCE_CANDIDATES=" + str(len(report["performance_candidates"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
