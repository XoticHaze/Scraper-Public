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
        if exact_id:
            # A source-curated alias applies only to the same exact identifier.
            # Never use it to match a title, a different identifier, or a wrong model.
            aliases = row.get("exact_id_brand_aliases") or []
            if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
                continue
            allowed = {str(row.get("brand") or "").strip().casefold()}
            allowed.update(a.strip().casefold() for a in aliases if a.strip())
            if (brand and brand not in allowed) or (model and model != str(row.get("model") or "").casefold()):
                continue
        if exact_id or (exact_model and not row.get("require_exact_identifier")):
            matches.append({**row, "identity_basis": "exact_identifier" if exact_id else "structured_brand_model"})
    return matches[0] if len(matches) == 1 else None
