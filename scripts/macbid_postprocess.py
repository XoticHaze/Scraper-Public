from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deal_engine.grouping import collapse_ranked, product_identity

REPORT = Path("results/macbid-deal-engine.json")


def condition_rank(condition: str, config: dict[str, Any]) -> int:
    ranking = config.get("condition_priority", {})
    try:
        return int(ranking.get(condition.upper(), 999))
    except Exception:
        return 999


def close_date_key(lot: dict[str, Any]) -> str:
    value = lot.get("expected_close_date")
    return str(value) if value else "9999-12-31"


def main() -> int:
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    config = data.get("policy", {})
    inventory = list(data.get("inventory", []))
    limits = config.get("views", {})

    ending = sorted(
        inventory,
        key=lambda x: (
            close_date_key(x),
            condition_rank(str(x.get("condition") or ""), config),
            -float(x.get("deal_score") or 0),
        ),
    )
    best = sorted(
        inventory,
        key=lambda x: (
            -float(x.get("deal_score") or 0),
            condition_rank(str(x.get("condition") or ""), config),
            close_date_key(x),
        ),
    )
    low_comp = sorted(
        inventory,
        key=lambda x: (
            int(x.get("unique_bidders") or 0),
            int(x.get("total_bids") or 0),
            -float(x.get("deal_score") or 0),
            close_date_key(x),
        ),
    )

    collapsed_ending = collapse_ranked(ending)
    collapsed_best = collapse_ranked(best)
    collapsed_low = collapse_ranked(low_comp)

    verification = []
    for lot in collapsed_best[:100]:
        candidate = dict(lot)
        candidate["market_price_status"] = "unverified"
        candidate["candidate_score_kind"] = "discovery_only"
        candidate["next_gate"] = "verify exact product/model and current market price before bid recommendation"
        verification.append(candidate)

    data["views"] = {
        "ending_soon": collapsed_ending[: int(limits.get("ending_soon", 100))],
        "best_value": collapsed_best[: int(limits.get("best_value", 100))],
        "low_competition": collapsed_low[: int(limits.get("low_competition", 100))],
        "verification_queue": verification,
    }
    data.setdefault("scan", {})["unique_product_candidates"] = len({product_identity(lot) for lot in inventory})
    data["scan"]["duplicate_lots_collapsed"] = len(inventory) - data["scan"]["unique_product_candidates"]

    REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"POSTPROCESS_UNIQUE_PRODUCTS={data['scan']['unique_product_candidates']}")
    print(f"POSTPROCESS_DUPLICATE_LOTS={data['scan']['duplicate_lots_collapsed']}")
    for view, rows in data["views"].items():
        print(f"POSTPROCESS_VIEW {view} count={len(rows)}")
        for lot in rows[:10]:
            print(
                json.dumps(
                    {
                        "product_name": lot.get("product_name") or lot.get("title") or lot.get("name"),
                        "condition": lot.get("condition"),
                        "current_bid": lot.get("current_bid"),
                        "retail_price": lot.get("retail_price"),
                        "expected_close_date": lot.get("expected_close_date"),
                        "unique_bidders": lot.get("unique_bidders"),
                        "duplicate_lot_count": lot.get("duplicate_lot_count"),
                        "macbid_url": lot.get("macbid_url"),
                    },
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
