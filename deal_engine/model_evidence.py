"""Source-linked model evidence; no title-only identity or purchase authority."""
from __future__ import annotations

def match_model_evidence(product, rows):
    identity = str(product.get("identity") or "").strip().lower()
    brand = str(product.get("brand") or "").strip().casefold()
    model = str(product.get("model") or "").strip().casefold()
    matches = []
    for row in rows:
        exact_id = identity and identity in {str(i).lower() for i in row.get("identities", [])}
        exact_model = brand and model and brand == str(row.get("brand") or "").casefold() and model == str(row.get("model") or "").casefold()
        if exact_id or exact_model:
            matches.append({**row, "identity_basis": "exact_identifier" if exact_id else "structured_brand_model"})
    return matches[0] if len(matches) == 1 else None
