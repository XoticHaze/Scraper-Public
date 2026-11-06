"""Read-only marketplace adapters; ingestion is opt-in and no retailer hunts are configured."""
from .normalizers import ebay_risk, normalize_ebay_item, normalize_bestbuy_products, normalize_bestbuy_open_box

__all__ = ["ebay_risk", "normalize_ebay_item", "normalize_bestbuy_products", "normalize_bestbuy_open_box"]
