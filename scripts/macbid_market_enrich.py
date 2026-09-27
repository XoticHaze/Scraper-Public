from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from deal_engine.grouping import product_identity
from deal_engine.hunts import match_profiles
from deal_engine.market_enrichment import (
    candidate_priority_score,
    identity_kind,
    merge_current_observation,
    merged_market_records,
    normalize_identity,
    select_observation_price,
    update_confidence,
)

REPORT = Path("results/macbid-deal-engine.json")
CANONICAL = Path("app/market_values.json")
CONFIG = Path("config/market_enrichment.json")
HUNTS = Path("app/hunts.json")
OUTPUT = Path("results/market-values.runtime.json")

USER_AGENT = "Mozilla/5.0 (compatible; Scraper-Public-MarketEnrichment/1.0; +https://github.com/XoticHaze/Scraper-Public)"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _fetch_bytes(url: str, *, timeout: int, max_bytes: int) -> tuple[str, str] | None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("content-type") or "").lower()
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return None
            return response.geturl(), raw.decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"MARKET_FETCH=MISS url={url} reason={type(exc).__name__}")
        return None


def _load_previous(url: str, *, timeout: int, max_bytes: int) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return None
        doc = json.loads(raw.decode("utf-8"))
        if doc.get("schema") != "macbid-market-values-v1":
            return None
        print(f"MARKET_PREVIOUS=PASS valuations={len(doc.get('valuations') or [])}")
        return doc
    except Exception as exc:
        print(f"MARKET_PREVIOUS=UNAVAILABLE reason={type(exc).__name__}")
        return None


def _record_token(record: dict[str, Any]) -> str:
    identity = str(record.get("identity") or "")
    if ":" in identity:
        return identity.split(":", 1)[1].strip()
    return identity.strip()


def _candidate_product(lot: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": product_identity(lot),
        "name": lot.get("product_name") or lot.get("title") or lot.get("name") or "",
        "brand": lot.get("brand") or lot.get("manufacturer"),
        "category": lot.get("category"),
        "upc": lot.get("upc"),
        "model": lot.get("model_number") or lot.get("model"),
        "retail_price": lot.get("retail_price") or lot.get("retail"),
    }


def _candidate_token(lot: dict[str, Any]) -> str | None:
    for value in (lot.get("upc"), lot.get("model_number"), lot.get("model")):
        token = str(value or "").strip()
        if identity_kind(token) in {"asin", "gtin"}:
            return token
    return None


def _candidate_rows(
    report: dict[str, Any],
    profiles: list[dict[str, Any]],
    existing: set[str],
    limit: int,
    profile_priority: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    seen: set[str] = set()

    # Hunt-matched live inventory first, then the generic verification queue.
    pools = [
        list(report.get("inventory") or []),
        list((report.get("views") or {}).get("verification_queue") or []),
    ]
    for pool_index, pool in enumerate(pools):
        for lot in pool:
            identity = product_identity(lot)
            if identity in seen or identity in existing:
                continue
            token = _candidate_token(lot)
            if not token:
                continue
            product = _candidate_product(lot)
            matches = match_profiles(profiles, product, lot)
            if pool_index == 0 and not matches:
                continue
            score = candidate_priority_score(
                matches,
                lot.get("deal_score"),
                profile_priority=profile_priority,
            )
            if pool_index == 1 and not matches:
                score += 10.0
            ranked.append((score, {**lot, "_candidate_identity": identity, "_candidate_token": token}))
            seen.add(identity)

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [row for _, row in ranked[:limit]]


def _provider_url(provider: dict[str, Any], token: str) -> str:
    return str(provider.get("url_template") or "").replace("{id}", token)


def _provider_supports(provider: dict[str, Any], token: str) -> bool:
    kind = identity_kind(token)
    return kind is not None and kind in set(provider.get("identity_kinds") or [])


def _extract_observation(
    provider: dict[str, Any],
    token: str,
    *,
    timeout: int,
    max_bytes: int,
) -> dict[str, Any] | None:
    url = _provider_url(provider, token)
    fetched = _fetch_bytes(url, timeout=timeout, max_bytes=max_bytes)
    if not fetched:
        return None
    final_url, html = fetched
    identity_in_url = bool(provider.get("identity_in_url")) and (
        normalize_identity(token) in normalize_identity(final_url)
        or normalize_identity(token) in normalize_identity(url)
    )
    if provider.get("identity_in_url") and not identity_in_url:
        print(f"MARKET_IDENTITY=REDIRECT_REJECT provider={provider.get('id')} token={token}")
        return None

    price, extraction = select_observation_price(
        html,
        identity=token,
        identity_in_url=identity_in_url,
        price_labels=list(provider.get("price_labels") or []),
    )
    if price is None:
        print(f"MARKET_PRICE=MISS provider={provider.get('id')} token={token}")
        return None
    return {
        "condition": "new",
        "price": round(float(price), 2),
        "source_label": provider.get("label") or provider.get("id"),
        "url": final_url,
        "observed_at": time.strftime("%Y-%m-%d", time.gmtime()),
        "provider": provider.get("id"),
        "extraction": extraction,
    }


def _refresh_existing(
    market: dict[str, Any],
    providers: list[dict[str, Any]],
    *,
    timeout: int,
    max_bytes: int,
    limit: int,
) -> tuple[int, int]:
    attempted = 0
    refreshed = 0
    for record in market.get("valuations") or []:
        token = _record_token(record)
        if not token:
            continue
        model = str(record.get("model") or "")
        for old in list(record.get("observations") or []):
            if attempted >= limit:
                return attempted, refreshed
            url = str(old.get("url") or "")
            if not url:
                continue
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if str(old.get("observed_at") or "") == today:
                continue
            attempted += 1
            fetched = _fetch_bytes(url, timeout=timeout, max_bytes=max_bytes)
            if not fetched:
                continue
            final_url, html = fetched
            exact_in_url = (
                normalize_identity(token) in normalize_identity(final_url)
                or (model and normalize_identity(model) in normalize_identity(final_url))
            )
            price, extraction = select_observation_price(
                html,
                identity=token,
                identity_in_url=exact_in_url,
                price_labels=["current price", "amazon price", "today's price"],
            )
            if price is None and model:
                price, extraction = select_observation_price(
                    html,
                    identity=model,
                    identity_in_url=exact_in_url,
                    price_labels=["current price", "amazon price", "today's price"],
                )
            if price is None:
                continue
            observation = {
                **old,
                "price": round(float(price), 2),
                "url": final_url,
                "observed_at": time.strftime("%Y-%m-%d", time.gmtime()),
                "extraction": extraction,
            }
            merge_current_observation(record, observation)
            refreshed += 1
        update_confidence(record)
    return attempted, refreshed


def _recent_attempts(market: dict[str, Any], retry_after_hours: int) -> set[str]:
    now = time.time()
    skip: set[str] = set()
    for identity, row in (market.get("enrichment_attempts") or {}).items():
        try:
            attempted_epoch = float(row.get("attempted_epoch") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if attempted_epoch > 0 and now - attempted_epoch < retry_after_hours * 3600:
            skip.add(str(identity))
    return skip


def main() -> int:
    report = _read_json(REPORT, {})
    canonical = _read_json(CANONICAL, {"schema": "macbid-market-values-v1", "valuations": []})
    config = _read_json(CONFIG, {"enabled": False, "providers": []})
    hunt_doc = _read_json(HUNTS, {"profiles": []})
    if not config.get("enabled", False):
        OUTPUT.write_text(json.dumps(canonical, indent=2) + "\n", encoding="utf-8")
        print("MARKET_ENRICH=DISABLED")
        return 0

    timeout = int(config.get("request_timeout_seconds") or 7)
    max_bytes = int(config.get("max_response_bytes") or 3_000_000)
    previous = _load_previous(
        str(config.get("live_previous_url") or ""),
        timeout=timeout,
        max_bytes=max_bytes,
    )
    market = merged_market_records(canonical, previous)
    providers = list(config.get("providers") or [])

    refresh_attempted, refreshed = _refresh_existing(
        market,
        providers,
        timeout=timeout,
        max_bytes=max_bytes,
        limit=int(config.get("max_existing_sources_per_run") or 24),
    )

    records = {
        str(row.get("identity")): row
        for row in (market.get("valuations") or [])
        if isinstance(row, dict) and row.get("identity")
    }
    retry_after_hours = int(config.get("retry_after_hours") or 24)
    cooldown = _recent_attempts(market, retry_after_hours)
    candidates = _candidate_rows(
        report,
        list(hunt_doc.get("profiles") or []),
        set(records) | cooldown,
        int(config.get("max_candidates_per_run") or 16),
        profile_priority=dict(config.get("profile_priority") or {}),
    )
    attempts = dict(market.get("enrichment_attempts") or {})

    searched = 0
    promoted = 0
    observations_added = 0
    for candidate in candidates:
        identity = str(candidate["_candidate_identity"])
        token = str(candidate["_candidate_token"])
        observations = []
        for provider in providers:
            if not _provider_supports(provider, token):
                continue
            searched += 1
            observation = _extract_observation(
                provider,
                token,
                timeout=timeout,
                max_bytes=max_bytes,
            )
            if observation:
                observations.append(observation)
                observations_added += 1

        attempts[identity] = {
            "token": token,
            "attempted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "attempted_epoch": int(time.time()),
            "successful": bool(observations),
            "providers": [
                str(provider.get("id"))
                for provider in providers
                if _provider_supports(provider, token)
            ],
        }
        if not observations:
            continue
        record = {
            "identity": identity,
            "model": candidate.get("model_number") or candidate.get("model") or candidate.get("product_name"),
            "status": "verified_external",
            "identity_confidence": "high",
            "price_confidence": "unknown",
            "observed_at": time.strftime("%Y-%m-%d", time.gmtime()),
            "risk_note": "Auto-promoted from exact-identity external pricing. Verify condition, completeness, compatibility, and category-specific risk before purchase.",
            "automation": {
                "promotion": "exact_identity_provider",
                "token": token,
            },
            "observations": [],
        }
        for observation in observations:
            merge_current_observation(record, observation)
        update_confidence(record)
        records[identity] = record
        promoted += 1

    market["valuations"] = sorted(records.values(), key=lambda row: str(row.get("identity") or ""))
    market["enrichment_attempts"] = attempts
    market["updated_at"] = time.strftime("%Y-%m-%d", time.gmtime())
    market["runtime_enrichment"] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refresh_attempted": refresh_attempted,
        "refreshed": refreshed,
        "candidates": len(candidates),
        "cooldown_skipped": len(cooldown),
        "provider_searches": searched,
        "promoted": promoted,
        "observations_added": observations_added,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(market, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"MARKET_ENRICH_VALUATIONS={len(market['valuations'])}")
    print(f"MARKET_ENRICH_REFRESH attempted={refresh_attempted} refreshed={refreshed}")
    print(f"MARKET_ENRICH_CANDIDATES={len(candidates)} searches={searched} promoted={promoted} observations={observations_added}")
    print(f"MARKET_ENRICH_OUTPUT={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
