"""Checksum-bound, public legacy candidates. Never infer a close from disappearance."""
import hashlib
import json
from pathlib import Path

from deal_engine.grouping import product_identity
from deal_engine.hunts import match_profiles
from deal_engine.historical_reconciliation import canonical_lot_url, lot_key

ROOT = Path("data/macbid-recovered-legacy-v2")
SCOPE = "recovered-legacy-retail-floor-40"

def load_expanded_seed(root=ROOT, profiles=None):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["schema"] != "macbid-recovered-legacy-v2" or manifest["scope_id"] != SCOPE:
        raise ValueError("unexpected recovered seed schema")
    fields = manifest["fields"]
    if profiles is None:
        profiles = json.loads(Path("app/hunts.json").read_text())["profiles"]
    rows, seen = [], set()
    digest = hashlib.sha256()
    for i, part in enumerate(manifest["parts"]):
        if part["path"] != f"part-{i:02d}.jsonl":
            raise ValueError("invalid shard path")
        raw = (root / part["path"]).read_bytes()
        if len(raw) != part["bytes"] or hashlib.sha256(raw).hexdigest() != part["sha256"]:
            raise ValueError("recovered seed checksum mismatch")
        digest.update(raw)
        lines = raw.splitlines()
        if len(lines) != part["count"]:
            raise ValueError("recovered seed count mismatch")
        for line in lines:
            values = json.loads(line)
            if len(values) != len(fields):
                raise ValueError("recovered row field mismatch")
            row = dict(zip(fields, values))
            key, url = lot_key(row), canonical_lot_url(row)
            if (not all(key) or not key[0].isdigit() or not url or key in seen
                    or row["auction_location"] != "San Antonio"
                    or not row["source_epoch_utc"] < row["expected_closing_utc"] <= row["first_missing_epoch_utc"]):
                raise ValueError("invalid recovered row")
            seen.add(key)
            row.update(identity=product_identity(row), macbid_url=url,
                       hunt_ids=list(match_profiles(profiles, row, row)),
                       scope_id=SCOPE, status="missing_unresolved",
                       hunt_match_provenance="retrospective_current_profiles")
            rows.append(row)
    if len(rows) != manifest["count"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("recovered aggregate mismatch")
    return rows
