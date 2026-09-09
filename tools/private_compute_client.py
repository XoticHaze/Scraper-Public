from __future__ import annotations

import argparse
import json
from pathlib import Path

from encrypted_compute.client import decrypt_result, prepare_workload, safe_extract_result


def cmd_prepare(args: argparse.Namespace) -> None:
    recipient = json.loads(Path(args.recipient).read_text(encoding="utf-8"))
    run_id = str(recipient["run_id"])
    contract_id = str(recipient["contract_id"])
    response_root = f"rendezvous/responses/{run_id}/{contract_id}"
    prepared = prepare_workload(
        recipient=recipient,
        payload_dir=Path(args.payload_dir),
        entrypoint=args.entrypoint,
        response_root=response_root,
    )
    out = Path(args.out)
    upload = out / "upload"
    chunks = upload / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    (upload / "workload-envelope.json").write_text(
        json.dumps(prepared["envelope"], sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for path, body in prepared["chunk_files"]:
        (chunks / Path(path).name).write_text(body, encoding="ascii")
    private_dir = out / "PRIVATE_DO_NOT_UPLOAD"
    private_dir.mkdir(parents=True, exist_ok=True)
    key_path = private_dir / "result-private-key.b64"
    key_path.write_text(prepared["result_private_key_b64"] + "\n", encoding="ascii")
    key_path.chmod(0o600)
    metadata = {
        "schema": "repo-app-private-compute-client-state-v1",
        "run_id": run_id,
        "contract_id": contract_id,
        "contract_version": str(recipient["contract_version"]),
        "response_root": response_root,
        "result_root": f"rendezvous/results/{run_id}/{contract_id}",
        "workload_plaintext_sha256": prepared["workload_plaintext_sha256"],
        "result_recipient_key_id": prepared["result_recipient"]["recipient_key_id"],
    }
    (private_dir / "state.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"prepared": True, "run_id": run_id, "contract_id": contract_id, "upload_dir": str(upload)}, sort_keys=True))


def cmd_decrypt(args: argparse.Namespace) -> None:
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    envelope = json.loads(Path(args.envelope).read_text(encoding="utf-8"))
    chunks_dir = Path(args.chunks_dir)
    chunks = {str(node["path"]): (chunks_dir / Path(str(node["path"])).name).read_text(encoding="ascii") for node in envelope["chunks"]}
    private_key = Path(args.private_key).read_text(encoding="ascii").strip()
    result = decrypt_result(
        envelope=envelope,
        chunks=chunks,
        result_private_key_b64=private_key,
        run_id=str(state["run_id"]),
        contract_id=str(state["contract_id"]),
        contract_version=str(state["contract_version"]),
        result_root=str(state["result_root"]),
    )
    safe_extract_result(result, Path(args.out))
    print(json.dumps({"decrypted": True, "run_id": state["run_id"], "contract_id": state["contract_id"], "output_dir": args.out}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare/decrypt run-bound private compute capsules")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--recipient", required=True)
    prepare.add_argument("--payload-dir", required=True)
    prepare.add_argument("--entrypoint", default="entrypoint.py")
    prepare.add_argument("--out", required=True)
    prepare.set_defaults(func=cmd_prepare)

    decrypt = sub.add_parser("decrypt-result")
    decrypt.add_argument("--state", required=True)
    decrypt.add_argument("--private-key", required=True)
    decrypt.add_argument("--envelope", required=True)
    decrypt.add_argument("--chunks-dir", required=True)
    decrypt.add_argument("--out", required=True)
    decrypt.set_defaults(func=cmd_decrypt)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
