"""Export a working offline storefront preview from a proven source snapshot.

Builds a browser-openable bundle without depending on MAC.BID's Pages
deployment or a local server. It only includes the auctioneer's Buy It Now
catalog, never HiBid auction lots or private account state.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

SRC = Path("results/paotexas-store.json")
UI = Path("ui")


def export(source: Path, output: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if (payload.get("schema") != "scraper-storefront-catalog-v1"
            or payload.get("source_type") != "buy_it_now_not_hibid_auction"
            or int(payload.get("product_count") or 0) < 1):
        raise RuntimeError("unverified storefront source; offline bundle not built")
    output.mkdir(parents=True, exist_ok=True)
    html = (UI / "paotexas.html").read_text(encoding="utf-8")
    # In an offline ZIP, local index.html is the store view, not MAC.BID Hunt.
    # Point cross-app navigation at the existing published Scraper Pages.
    origin = "https://xotichaze.github.io/Scraper-Public/"
    for local in ("index.html", "vehicles.html", "finds.html"):
        html = html.replace(f'href="{local}"', f'href="{origin}{local}"')
    script = '<script src="paotexas-catalog.js"></script>\n  <script src="paotexas.js"'
    if '<script src="paotexas.js"' not in html:
        raise RuntimeError("missing source browser script")
    html = html.replace('<script src="paotexas.js"', script)
    (output / "index.html").write_text(html, encoding="utf-8")
    (output / "paotexas.html").write_text(html, encoding="utf-8")
    for asset in ("paotexas.js", "paotexas.css"):
        shutil.copyfile(UI / asset, output / asset)
    (output / "paotexas-catalog.js").write_text(
        "window.PAOTEXAS_STORE_CATALOG=" +
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"OFFLINE_PAOTEXAS_PRODUCTS={payload['product_count']}")
    print(f"OFFLINE_PAOTEXAS_OUTPUT={output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SRC))
    parser.add_argument("--output", default="paotexas-preview")
    args = parser.parse_args()
    export(Path(args.source), Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
