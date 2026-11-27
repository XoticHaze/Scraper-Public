from __future__ import annotations

import json
import os
import time
import urllib.request
from urllib.parse import urlparse, unquote
from pathlib import Path
from typing import Any

from deal_engine.grouping import product_identity
from deal_engine.valuation import summarize_market_value
from deal_engine.public_artifact_state import prior_public_artifacts, read_public_artifact_json
from deal_engine.hunts import match_profiles
from deal_engine.model_evidence import match_model_evidence
from deal_engine.market_enrichment import (
    candidate_priority_score,
    identity_kind,
    merge_current_observation,
    merged_market_records,
    normalize_identity,
    select_observation_price,
    update_confidence,
    source_domain,
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


def _previous_state(config: dict[str, Any], *, timeout: int) -> tuple[dict[str, Any] | None, str]:
    bound = int(config.get("max_previous_bytes") or 30_000_000)
    previous = _load_previous(str(config.get("live_previous_url") or ""), timeout=timeout, max_bytes=bound)
    if previous is not None and not isinstance(previous.get("valuations"), list):
        previous = None
    if os.environ.get("GITHUB_REPOSITORY") == "XoticHaze/Scraper-Public":
        try:
            artifacts = prior_public_artifacts("macbid-deal-engine")
            for artifact in artifacts[:3]:
                published = str((previous or {}).get("runtime_enrichment", {}).get("generated_at") or "")
                if previous is not None and published and str(artifact.get("created_at") or "")[:16] <= published[:16]:
                    break
                try:
                    recovered = read_public_artifact_json(artifact, name="macbid-deal-engine", max_bytes=bound)
                    if recovered.get("schema") != "macbid-market-values-v1" or not isinstance(recovered.get("valuations"), list):
                        continue
                    if previous is None or str(recovered.get("runtime_enrichment", {}).get("generated_at") or "") > published:
                        print("MARKET_PREVIOUS=ARTIFACT run=" + str(artifact["workflow_run"]["id"]))
                        return recovered, "prior_public_artifact"
                    break
                except Exception as exc:
                    print("MARKET_ARTIFACT=MISS reason=" + type(exc).__name__)
        except Exception as exc:
            print("MARKET_ARTIFACT=UNAVAILABLE reason=" + type(exc).__name__)
        if previous is None and config.get("require_previous_state", True):
            raise RuntimeError("No prior public valuation state available; refusing to reset accumulated evidence")
    return previous, "pages" if previous is not None else "canonical_only"


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
    for value in (lot.get("upc"), lot.get("asin"), lot.get("model_number"), lot.get("model")):
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
    profile_attempts: dict[str, float] | None = None,
    coverage: dict[str, int] | None = None,
    model_evidence_rows: list[dict[str, Any]] | None = None,
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
            evidence = match_model_evidence(product, model_evidence_rows or [])
            if evidence:
                product["model_evidence"] = evidence
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
            ranked.append((score, {**lot, "_candidate_identity": identity, "_candidate_token": token, "_candidate_profiles": sorted(matches)}))
            seen.add(identity)

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    # Reserve one slot for rotating non-primary hunts, without displacing the pilot.
    if limit <= 0:
        return []
    pilot = set((profile_priority or {}).get("pilot") or [])
    # Guarantee a bounded pilot allocation, while leaving most capacity for other hunts.
    pilot_rows = [row for _, row in ranked if pilot.intersection(row["_candidate_profiles"])]
    selected = pilot_rows[:min(3, max(1, limit // 4))]
    selected_ids = {row["_candidate_identity"] for row in selected}
    represented = {p for row in selected for p in row["_candidate_profiles"]}
    pool_counts = {str(p["id"]): 0 for p in profiles}
    for _, row in ranked:
        for pid in row["_candidate_profiles"]:
            pool_counts[pid] = pool_counts.get(pid, 0) + 1
    if coverage is not None:
        coverage.update(pool_counts)
    # Use persistent attempt dates, not a wall-clock modulo that can starve hunts.
    fair_slots = min(4, max(0, limit - len(selected)), limit // 3)
    for _ in range(fair_slots):
        options = [row for _, row in ranked if row["_candidate_identity"] not in selected_ids]
        targets = {pid for row in options for pid in row["_candidate_profiles"] if pid not in represented and pid not in pilot}
        if not targets:
            break
        target = min(targets, key=lambda p: ((profile_attempts or {}).get(p, 0), pool_counts.get(p, 0), p))
        row = next(row for row in options if target in row["_candidate_profiles"])
        selected.append(row)
        selected_ids.add(row["_candidate_identity"])
        represented.update(row["_candidate_profiles"])
    selected += [row for _, row in ranked if row["_candidate_identity"] not in selected_ids][:limit - len(selected)]
    return selected


def _provider_url(provider: dict[str, Any], token: str) -> str:
    return str(provider.get("url_template") or "").replace("{id}", token)


def _provider_supports(provider: dict[str, Any], token: str) -> bool:
    kind = identity_kind(token)
    return kind is not None and kind in set(provider.get("identity_kinds") or [])


def _exact_path_token(url: str, token: str) -> bool:
    return token.lower() in {unquote(part).lower() for part in urlparse(url).path.split("/") if part}


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
    if source_domain(final_url) != source_domain(url):
        return None
    identity_in_url = bool(provider.get("identity_in_url")) and (
        _exact_path_token(final_url, token)
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
    active_identities: set[str] | None = None,
) -> tuple[int, int]:
    attempted = 0
    refreshed = 0
    active = active_identities or set()
    allowed_domains = {source_domain(str(p.get('url_template') or '')) for p in providers}
    records = sorted(market.get("valuations") or [], key=lambda r: (str(r.get("identity")) not in active, str(r.get("last_refresh_attempt_at") or ""), str(r.get("identity") or "")))
    for record in records:
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
            # Refresh only registered new-price sources, never merchant or secondary-market pages.
            if str(old.get('condition') or '').lower() != 'new' or source_domain(url) not in allowed_domains or not url.startswith('https://'):
                continue
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if str(old.get("observed_at") or "") == today:
                continue
            attempted += 1
            record["last_refresh_attempt_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fetched = _fetch_bytes(url, timeout=timeout, max_bytes=max_bytes)
            if not fetched:
                continue
            final_url, html = fetched
            if source_domain(final_url) != source_domain(url):
                continue
            exact_in_url = _exact_path_token(final_url, token)
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
    previous, previous_source = _previous_state(config, timeout=timeout)
    market = merged_market_records(canonical, previous)
    providers = list(config.get("providers") or [])

    refresh_attempted, refreshed = _refresh_existing(
        market,
        providers,
        timeout=timeout,
        max_bytes=max_bytes,
        limit=int(config.get("max_existing_sources_per_run") or 24),
        active_identities={product_identity(lot) for lot in (report.get("inventory") or [])},
    )

    records = {
        str(row.get("identity")): row
        for row in (market.get("valuations") or [])
        if isinstance(row, dict) and row.get("identity")
    }
    retry_after_hours = int(config.get("retry_after_hours") or 24)
    cooldown = _recent_attempts(market, retry_after_hours)
    attempts = dict(market.get('enrichment_attempts') or {})
    profile_attempts = {}
    for row in attempts.values():
        for pid in row.get('profiles', []):
            profile_attempts[pid] = max(profile_attempts.get(pid, 0), float(row.get('attempted_epoch') or 0))
    eligible_counts = {}
    # Identity-only and stale records may be retried without losing manual metadata.
    current_records = {k for k, row in records.items() if summarize_market_value(row, as_of=time.strftime('%Y-%m-%d', time.gmtime())).get('current_source_count')}
    candidates = _candidate_rows(
        report,
        list(hunt_doc.get("profiles") or []),
        current_records | cooldown,
        int(config.get("max_candidates_per_run") or 16),
        profile_priority=dict(config.get("profile_priority") or {}),
        profile_attempts=profile_attempts, coverage=eligible_counts,
        model_evidence_rows=_read_json(Path("app/research_findings.json"), {}).get("model_evidence", []),
    )

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
            "profiles": candidate["_candidate_profiles"],
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
        record = {**record, **records.get(identity, {})}
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
        "provider_misses": searched - observations_added,
        "refresh_misses": refresh_attempted - refreshed,
        "previous_runtime_loaded": previous is not None,
        "previous_runtime_source": previous_source,
        "eligible_candidate_profiles": eligible_counts,
        "candidate_profiles": {str(profile["id"]): sum(str(profile["id"]) in c["_candidate_profiles"] for c in candidates) for profile in (hunt_doc.get("profiles") or [])},
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
