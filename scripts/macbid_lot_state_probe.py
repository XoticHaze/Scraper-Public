from __future__ import annotations

import json
import urllib.request
from typing import Any

LOT_IDS = (63270389, 63488024, 63272232)
BASE = "https://api.macdiscount.com/map-bid/ddb/lot/{lot_id}"
SENSITIVE = {"email", "phone", "address", "token", "cookie", "authorization", "user", "bidder"}


def sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return type(value).__name__
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            key_s = str(key)
            if any(term in key_s.lower() for term in SENSITIVE):
                continue
            out[key_s] = sanitize(child, depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize(v, depth + 1) for v in value[:10]]
    if isinstance(value, str):
        return value[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


def main() -> int:
    for lot_id in LOT_IDS:
        url = BASE.format(lot_id=lot_id)
        req = urllib.request.Request(url, headers={"User-Agent": "Scraper-Public/1.0 public-catalog-probe"})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8"))
                print(f"LOT_STATE_STATUS lot_id={lot_id} status={response.status}")
                print("LOT_STATE " + json.dumps({"lot_id": lot_id, "data": sanitize(data)}, sort_keys=True))
        except Exception as exc:
            print(f"LOT_STATE_ERROR lot_id={lot_id} error={type(exc).__name__}:{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
