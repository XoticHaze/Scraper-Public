from __future__ import annotations

import json
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from deal_engine.compatibility import compatibility_allows_hunt, evaluate_compatibility
from deal_engine.grouping import product_identity
from deal_engine.hunts import match_profiles
from deal_engine.valuation import derive_market_valuation, summarize_market_value

REPORT = Path("results/macbid-deal-engine.json")
UI_SOURCE = Path("ui")
APP_ACTIONS = Path("app/actions.json")
APP_HUNTS = Path("app/hunts.json")
APP_FINDINGS = Path("app/research_findings.json")
APP_COMPATIBILITY = Path("app/compatibility_matrix.json")
APP_MARKET_VALUES = Path("app/market_values.json")
RUNTIME_MARKET_VALUES = Path("results/market-values.runtime.json")
SITE = Path("site")

LOT_FIELDS = (
    "lot_id",
    "id",
    "auction_number",
    "auction_title",
    "lot_number",
    "auction_location",
    "condition",
    "current_bid",
    "retail_price",
    "estimated_pre_tax_total",
    "estimated_sales_tax",
    "estimated_post_tax_total",
    "estimated_all_in_total",
    "sales_tax_rate",
    "stated_retail_discount_pct",
    "stated_retail_savings",
    "deal_score",
    "provisional_max_bid",
    "expected_close_date",
    "expected_closing_utc",
    "hours_until_close",
    "unique_bidders",
    "total_bids",
    "image_url",
    "stock_image_url",
    "macbid_url",
)

OPTIONAL_VERIFICATION_FIELDS = (
    "market_price_status",
    "verified_new_price",
    "realistic_open_box_value",
    "verified_discount_pct",
    "verified_savings",
    "verdict",
    "verified_max_bid",
    "max_bid",
    "current_new_average",
    "current_new_low",
    "current_new_high",
    "current_new_samples",
    "market_reference_value",
    "market_reference_basis",
    "market_value_confidence",
    "market_identity_confidence",
    "market_value_observed_at",
    "market_value_source_count",
    "allocation_ratio",
    "max_all_in",
    "market_value_age_days",
    "market_value_freshness",
    "market_value_authoritative",
)


def compact_lot(lot: dict[str, Any]) -> dict[str, Any]:
    out = {key: lot.get(key) for key in LOT_FIELDS if lot.get(key) is not None}
    for key in OPTIONAL_VERIFICATION_FIELDS:
        if lot.get(key) is not None:
            out[key] = lot.get(key)
    return out


def product_metadata(lots: list[dict[str, Any]]) -> dict[str, Any]:
    best = max(lots, key=lambda row: float(row.get("deal_score") or -10_000))
    metadata = {
        "identity": product_identity(best),
        "name": best.get("product_name") or best.get("title") or best.get("name") or "Unnamed item",
        "brand": best.get("brand") or best.get("manufacturer"),
        "category": best.get("category") or "Uncategorized",
        "upc": best.get("upc"),
        "model": best.get("model_number") or best.get("model"),
        "image_url": best.get("image_url") or best.get("stock_image_url"),
        "retail_price": best.get("retail_price") or best.get("retail"),
        "lot_count": len(lots),
    }
    for key in OPTIONAL_VERIFICATION_FIELDS:
        value = next((row.get(key) for row in lots if row.get(key) is not None), None)
        if value is not None:
            metadata[key] = value
    return metadata


def main() -> int:
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    scan = data.get("scan", {})
    policy = data.get("policy", {})
    final_epoch = int(scan.get("final_view_epoch_utc") or time.time())
    inventory = [
        lot
        for lot in data.get("inventory", [])
        if float(lot.get("expected_closing_utc") or 0) > final_epoch
    ]

    hunt_doc = json.loads(APP_HUNTS.read_text(encoding="utf-8")) if APP_HUNTS.exists() else {"profiles": []}
    profiles = hunt_doc.get("profiles") or []
    profile_counts = {str(profile["id"]): 0 for profile in profiles}
    finding_doc = json.loads(APP_FINDINGS.read_text(encoding="utf-8")) if APP_FINDINGS.exists() else {"findings": []}
    finding_map = {
        str(row["identity"]): row
        for row in (finding_doc.get("findings") or [])
        if isinstance(row, dict) and row.get("identity")
    }
    compatibility_doc = (
        json.loads(APP_COMPATIBILITY.read_text(encoding="utf-8"))
        if APP_COMPATIBILITY.exists()
        else {"schema": "macbid-compatibility-matrix-v1", "capability_rules": [], "vendor_rules": [], "exact_overrides": []}
    )
    market_source = RUNTIME_MARKET_VALUES if RUNTIME_MARKET_VALUES.exists() else APP_MARKET_VALUES
    market_doc = json.loads(market_source.read_text(encoding="utf-8")) if market_source.exists() else {"valuations": []}
    market_defaults = market_doc.get("defaults") or {}
    market_map = {
        str(row["identity"]): row
        for row in (market_doc.get("valuations") or [])
        if isinstance(row, dict) and row.get("identity")
    }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lot in inventory:
        grouped[product_identity(lot)].append(lot)

    products: list[dict[str, Any]] = []
    for lots in grouped.values():
        lots.sort(key=lambda row: float(row.get("expected_closing_utc") or float("inf")))
        product = product_metadata(lots)

        valuation = market_map.get(str(product["identity"]))
        if valuation and str(valuation.get("status") or "").lower() == "verified_external":
            market_summary = summarize_market_value(valuation)
            product["market_value"] = market_summary
            specs = market_summary.get("specs") or {}
            for key, value in specs.items():
                if value is not None:
                    product[key] = value

            for lot in lots:
                derived = derive_market_valuation(
                    valuation,
                    condition=str(lot.get("condition") or ""),
                    current_all_in=lot.get("estimated_post_tax_total") or lot.get("estimated_all_in_total"),
                    premium_rate=float(policy.get("buyer_premium_rate", 0.15)),
                    lot_fee=float(policy.get("lot_fee", 3.0)),
                    sales_tax_rate=float(policy.get("sales_tax_rate", 0.0)),
                    default_allocation_ratio=float(market_defaults.get("default_allocation_ratio", 0.65)),
                    like_new_fallback_ratio=float(market_defaults.get("like_new_fallback_ratio", 0.80)),
                    open_box_fallback_ratio=float(market_defaults.get("open_box_fallback_ratio", 0.75)),
                    as_of=time.strftime("%Y-%m-%d", time.gmtime(final_epoch)),
                    fresh_days=int(market_defaults.get("fresh_days", 7)),
                    stale_after_days=int(market_defaults.get("stale_after_days", 30)),
                )
                lot.update({key: value for key, value in derived.items() if value is not None})

            current_new = market_summary.get("current_new") or {}
            representative = lots[0] if lots else {}
            product["market_price_status"] = representative.get("market_price_status", "stale_external")
            product["market_value_age_days"] = representative.get("market_value_age_days")
            product["market_value_freshness"] = representative.get("market_value_freshness")
            product["market_value_authoritative"] = representative.get("market_value_authoritative", False)
            product["verified_new_price"] = current_new.get("median")
            product["current_new_average"] = current_new.get("average")
            product["current_new_low"] = current_new.get("low")
            product["current_new_high"] = current_new.get("high")
            product["current_new_samples"] = current_new.get("samples")
            product["market_value_confidence"] = market_summary.get("price_confidence")
            product["market_identity_confidence"] = market_summary.get("identity_confidence")
            product["market_value_observed_at"] = market_summary.get("observed_at")
            product["market_value_source_count"] = market_summary.get("source_count")
            secondary = market_summary.get("open_box_used") or {}
            if secondary.get("median") is not None:
                product["realistic_open_box_value"] = secondary.get("median")
            elif current_new.get("median") is not None:
                product["realistic_open_box_value"] = round(
                    float(current_new["median"]) * float(market_defaults.get("open_box_fallback_ratio", 0.75)),
                    2,
                )

        best_value_lot = max(
            lots,
            key=lambda row: (
                1 if row.get("market_price_status") == "verified_external" else 0,
                float(row.get("verified_discount_pct") or -10_000),
                float(row.get("deal_score") or -10_000),
            ),
        )
        compatibility = evaluate_compatibility(
            compatibility_doc,
            product,
            best_value_lot,
            target="haos",
        )
        product["compatibility"] = compatibility

        matches = match_profiles(profiles, product, best_value_lot)
        if matches:
            gated_out = {
                profile_id
                for profile_id, match in matches.items()
                if not compatibility_allows_hunt(compatibility, match.get("compatibility_gate"))
            }
            if gated_out:
                matches = {
                    profile_id: match
                    for profile_id, match in matches.items()
                    if profile_id not in gated_out
                }
                product["compatibility_suppressed_hunts"] = sorted(gated_out)

        # Model/market research is allowed to narrow semantic discovery. This is
        # deliberately one-way: a research note can suppress a disproven match,
        # but cannot silently manufacture a new hunt match.
        finding = finding_map.get(str(product["identity"]))
        suppressed = set(finding.get("suppress_hunts") or []) if finding else set()
        if suppressed:
            matches = {profile_id: match for profile_id, match in matches.items() if profile_id not in suppressed}
            product["research_suppressed_hunts"] = sorted(suppressed)

        if matches:
            product["hunt_matches"] = matches
            product["hunt_ids"] = list(matches)
            for profile_id in matches:
                profile_counts[profile_id] = profile_counts.get(profile_id, 0) + 1
        product["lots"] = [compact_lot(row) for row in lots]
        products.append(product)

    products.sort(
        key=lambda product: min(
            float(lot.get("expected_closing_utc") or float("inf")) for lot in product["lots"]
        )
    )

    public_profiles = []
    for profile in profiles:
        public_profiles.append(
            {
                "id": profile["id"],
                "label": profile["label"],
                "kind": profile.get("kind", "semantic"),
                "verification": profile.get("verification") or [],
                "compatibility_gate": profile.get("compatibility_gate"),
                "count": profile_counts.get(str(profile["id"]), 0),
            }
        )

    catalog = {
        "schema": "macbid-hunt-ui-v1",
        "generated_epoch_utc": int(time.time()),
        "source_scan_epoch_utc": scan.get("scan_epoch_utc"),
        "locations": policy.get("locations", []),
        "buyer_premium_rate": policy.get("buyer_premium_rate", 0.15),
        "lot_fee": policy.get("lot_fee", 3.0),
        "sales_tax_rate": policy.get("sales_tax_rate", 0.0),
        "sales_tax_scope": policy.get("sales_tax_scope"),
        "minimum_stated_retail": policy.get("minimum_stated_retail"),
        "product_count": len(products),
        "lot_count": len(inventory),
        "hunt_profiles": public_profiles,
        "market_value_count": sum(1 for product in products if product.get("market_price_status") == "verified_external"),
        "stale_market_value_count": sum(1 for product in products if product.get("market_price_status") == "stale_external"),
        "market_values_updated_at": market_doc.get("updated_at"),
        "market_value_authority": market_defaults.get("authority"),
        "compatibility_matrix_version": compatibility_doc.get("version"),
        "compatibility_counts": {
            status: sum(
                1
                for product in products
                if (product.get("compatibility") or {}).get("status") == status
            )
            for status in ("verified", "verified_with_requirements", "variant_required", "candidate", "unknown", "ruled_out")
        },
        "products": products,
    }

    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(UI_SOURCE, SITE)
    compact_json = json.dumps(catalog, separators=(",", ":"), ensure_ascii=False)
    (SITE / "catalog.json").write_text(compact_json, encoding="utf-8")
    (SITE / "catalog.js").write_text(
        "window.MACBID_CATALOG=" + compact_json + ";\n",
        encoding="utf-8",
    )
    if APP_ACTIONS.exists():
        actions = json.loads(APP_ACTIONS.read_text(encoding="utf-8"))
        (SITE / "actions.json").write_text(
            json.dumps(actions, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
    if APP_HUNTS.exists():
        (SITE / "hunt-profiles.json").write_text(
            json.dumps(hunt_doc, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
    if APP_COMPATIBILITY.exists():
        (SITE / "compatibility-matrix.json").write_text(
            json.dumps(compatibility_doc, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
    if market_source.exists():
        compact_market = json.dumps(market_doc, separators=(",", ":"), ensure_ascii=False)
        (SITE / "market-values.json").write_text(compact_market, encoding="utf-8")
    if APP_FINDINGS.exists():
        compact_findings = json.dumps(finding_doc, separators=(",", ":"), ensure_ascii=False)
        (SITE / "research-findings.json").write_text(compact_findings, encoding="utf-8")
        (SITE / "research-findings.js").write_text(
            "window.MACBID_RESEARCH_FINDINGS=" + compact_findings + ";\n",
            encoding="utf-8",
        )
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    print(f"UI_PRODUCTS={len(products)}")
    print(f"UI_LOTS={len(inventory)}")
    print(f"UI_HUNT_PROFILES={len(public_profiles)}")
    print(f"UI_RESEARCH_CORRECTIONS={sum(bool(p.get('research_suppressed_hunts')) for p in products)}")
    print(f"UI_SALES_TAX_RATE={catalog['sales_tax_rate']}")
    for profile in public_profiles:
        print(f"UI_HUNT {profile['id']}={profile['count']}")
    print(f"UI_ACTION_MANIFEST={'yes' if APP_ACTIONS.exists() else 'no'}")
    print(f"UI_RESEARCH_FINDINGS={'yes' if APP_FINDINGS.exists() else 'no'}")
    print(f"UI_COMPATIBILITY_COUNTS={json.dumps(catalog['compatibility_counts'], sort_keys=True)}")
    print(f"UI_MARKET_VALUES={catalog['market_value_count']}")
    print(f"UI_STALE_MARKET_VALUES={catalog['stale_market_value_count']}")
    print(f"UI_MARKET_VALUES_UPDATED_AT={catalog['market_values_updated_at']}")
    print(f"UI_MARKET_VALUES_SOURCE={market_source}")
    runtime_enrichment = market_doc.get("runtime_enrichment") or {}
    print(f"UI_MARKET_ENRICH promoted={runtime_enrichment.get('promoted', 0)} refreshed={runtime_enrichment.get('refreshed', 0)} searches={runtime_enrichment.get('provider_searches', 0)}")
    print(f"UI_OUTPUT={SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
