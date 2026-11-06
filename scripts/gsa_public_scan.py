"""Opt-in GSA Auctions official API probe, never bids or starts searches.

Uses documented DEMO_KEY only when --demo-probe is explicitly supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from deal_engine.marketplace.gsa import GSASourceError, build_gsa_catalog, fetch_gsa_auctions, _records


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--demo-probe", action="store_true", help="single documented DEMO_KEY read; no published catalog")
    p.add_argument("--state", choices=["TX"], help="filter public location by state")
    p.add_argument("--output", default="results/gsa-auctions.json")
    args = p.parse_args(argv)
    try:
        if args.demo_probe:
            payload = fetch_gsa_auctions(key="DEMO_KEY", timeout=25)
            try:
                records = _records(payload)
            except GSASourceError:
                # Schema diagnostic logs keys and value shapes only, never listing contents.
                def shape(obj, depth=0):
                    if depth > 2:
                        return type(obj).__name__
                    if isinstance(obj, dict):
                        return {str(k): shape(v, depth + 1) for k, v in list(obj.items())[:30]}
                    if isinstance(obj, list):
                        return {"type": "list", "count": len(obj),
                                "first_item_shape": shape(obj[0], depth + 1) if obj else None}
                    return type(obj).__name__
                print(json.dumps({"status": "GSA_RESPONSE_SCHEMA_CHANGED", "structure": shape(payload)}))
                raise
            # Log schema and count only. No location, description, or third-party URL data in logs.
            print(json.dumps({"status": "PROBE_RESPONSE_READ", "total_records": len(records),
                              "record_field_names": sorted(str(k) for k in records[0])[:45] if records else []}))
            return 0
        if not os.environ.get("GSA_API_KEY"):
            raise GSASourceError("GSA_API_KEY missing; not using DEMO_KEY in scheduled runs")
        doc = build_gsa_catalog(fetch_gsa_auctions(), state=args.state)
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"status": doc["source_status"], "count": doc["count"], "state": args.state}))
        return 0
    except GSASourceError as exc:
        print("GSA_SOURCE_UNAVAILABLE: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
