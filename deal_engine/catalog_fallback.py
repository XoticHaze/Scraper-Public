from __future__ import annotations

from typing import Any


def catalog_age_seconds(catalog: dict[str, Any], now_epoch: int) -> int | None:
    try:
        generated = int(catalog.get("generated_epoch_utc") or 0)
    except (TypeError, ValueError):
        return None
    if generated <= 0:
        return None
    return max(0, int(now_epoch) - generated)


def inventory_from_ui_catalog(
    catalog: dict[str, Any],
    *,
    now_epoch: int,
) -> list[dict[str, Any]]:
    """Rehydrate public lot rows from the last successful Pages catalog.

    This is deliberately a degraded fallback, not a replacement for a fresh
    MAC.BID scan. Closed lots are dropped using the canonical close epoch.
    """
    if catalog.get("schema") != "macbid-hunt-ui-v1":
        return []

    rows: list[dict[str, Any]] = []
    for product in catalog.get("products") or []:
        if not isinstance(product, dict):
            continue
        for lot in product.get("lots") or []:
            if not isinstance(lot, dict):
                continue
            try:
                closes = float(lot.get("expected_closing_utc") or 0)
            except (TypeError, ValueError):
                closes = 0
            if closes <= float(now_epoch):
                continue

            row = dict(lot)
            defaults = {
                "product_name": product.get("name"),
                "brand": product.get("brand"),
                "category": product.get("category"),
                "upc": product.get("upc"),
                "model": product.get("model"),
                "image_url": product.get("image_url"),
                "retail_price": product.get("retail_price"),
            }
            for key, value in defaults.items():
                if row.get(key) is None and value is not None:
                    row[key] = value
            rows.append(row)
    return rows


def fallback_catalog_is_usable(
    catalog: dict[str, Any],
    *,
    now_epoch: int,
    max_age_seconds: int,
) -> tuple[bool, int | None]:
    age = catalog_age_seconds(catalog, now_epoch)
    if age is None:
        return False, None
    if age > int(max_age_seconds):
        return False, age
    if not inventory_from_ui_catalog(catalog, now_epoch=now_epoch):
        return False, age
    return True, age
