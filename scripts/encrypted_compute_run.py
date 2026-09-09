from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.encrypted_compute_consumer import consume


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="config/encrypted_compute_contracts.json")
    parser.add_argument("--contract-id", required=True)
    parser.add_argument("--contract-version", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--chunk-map", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--response-root", required=True)
    parser.add_argument("--result-staging", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()

    try:
        receipt = consume(args)
        transport_ok = True
    except Exception as exc:  # Deliberately suppress private/path-bearing exception text.
        receipt = {
            "schema": "repo-app-encrypted-compute-receipt-v1",
            "contract_id": args.contract_id,
            "contract_version": args.contract_version,
            "run_id": str(args.run_id),
            "status": "ERROR",
            "error_class": type(exc).__name__,
            "private_plaintext_emitted": False,
            "stdout_stderr_public": False,
            "github_credentials_exposed_to_workload": False,
        }
        transport_ok = False

    receipt_path = Path(args.receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("ENCRYPTED_COMPUTE_PUBLIC_STATUS=" + receipt["status"])
    raise SystemExit(0 if transport_ok else 2)


if __name__ == "__main__":
    main()
