from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from encrypted_compute.client import decrypt_result, safe_extract_result
from encrypted_compute.transport import decrypt_bytes, generate_recipient, sha256_bytes
from scripts.encrypted_compute_consumer import consume


def node_interop(payload: dict) -> dict:
    proc = subprocess.run(
        ["node", "producer_worker/interop.mjs"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout)


def one_chunk_envelope(output: dict, *, root: str) -> tuple[dict, str]:
    ciphertext = base64.b64decode(output["ciphertext_b64"])
    chunk_body = base64.b64encode(ciphertext).decode("ascii")
    envelope = {
        **output["meta"],
        "chunks": [
            {
                "path": f"{root}/chunk-0000.b64",
                "sha256": sha256_bytes(chunk_body.encode("ascii")),
                "chars": len(chunk_body),
            }
        ],
    }
    return envelope, chunk_body


def test_node_producer_encrypts_payload_python_transport_can_decrypt():
    run_id = "99112233"
    contract_id = "python-bundle-v1"
    contract_version = "1"
    recipient = generate_recipient(
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        direction="workload",
    )
    plaintext = b"private producer cross-runtime interop proof\n"
    output = node_interop(
        {
            "recipient": recipient.public,
            "plaintext_b64": base64.b64encode(plaintext).decode("ascii"),
        }
    )
    ciphertext = base64.b64decode(output["ciphertext_b64"])
    root = f"rendezvous/responses/{run_id}/{contract_id}"
    envelope, _ = one_chunk_envelope(output, root=root)
    recovered = decrypt_bytes(
        envelope=envelope,
        ciphertext=ciphertext,
        private_key_b64=recipient.private_b64,
        expected_run_id=run_id,
        expected_contract_id=contract_id,
        expected_contract_version=contract_version,
        expected_direction="workload",
        response_root=root,
    )
    assert recovered == plaintext


def test_node_producer_full_capsule_executes_and_private_result_round_trips(tmp_path: Path):
    run_id = "99112234"
    contract_id = "python-bundle-v1"
    contract_version = "1"
    recipient = generate_recipient(
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        direction="workload",
    )
    output = node_interop({"mode": "full-workload", "recipient": recipient.public})
    response_root = f"rendezvous/responses/{run_id}/{contract_id}"
    envelope, chunk_body = one_chunk_envelope(output, root=response_root)

    envelope_path = tmp_path / "workload-envelope.json"
    chunk_map_path = tmp_path / "chunk-map.json"
    private_key_path = tmp_path / "runner-private.b64"
    result_staging = tmp_path / "encrypted-result"
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
    chunk_map_path.write_text(json.dumps({envelope["chunks"][0]["path"]: chunk_body}), encoding="utf-8")
    private_key_path.write_text(recipient.private_b64, encoding="ascii")

    receipt = consume(
        SimpleNamespace(
            registry="config/encrypted_compute_contracts.json",
            contract_id=contract_id,
            contract_version=contract_version,
            run_id=run_id,
            envelope=str(envelope_path),
            chunk_map=str(chunk_map_path),
            private_key=str(private_key_path),
            response_root=response_root,
            result_staging=str(result_staging),
        )
    )
    assert receipt["status"] == "PASS"
    assert receipt["private_plaintext_emitted"] is False
    assert receipt["stdout_stderr_public"] is False
    assert receipt["github_credentials_exposed_to_workload"] is False
    assert receipt["private_output_file_count"] == 1

    result_envelope = json.loads((result_staging / "result-envelope.json").read_text(encoding="utf-8"))
    result_chunks = {
        str(node["path"]): (result_staging / "chunks" / Path(str(node["path"])).name).read_text(encoding="ascii")
        for node in result_envelope["chunks"]
    }
    result_plaintext = decrypt_result(
        envelope=result_envelope,
        chunks=result_chunks,
        result_private_key_b64=output["result_private_raw_b64"],
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        result_root=f"rendezvous/results/{run_id}/{contract_id}",
    )
    extracted = tmp_path / "private-result"
    safe_extract_result(result_plaintext, extracted)
    assert (extracted / "output" / "proof.txt").read_text(encoding="utf-8") == "producer-full-round-trip-ok\n"
    assert "PRIVATE_NODE_PRODUCER_STDOUT" in (extracted / "execution" / "stdout.txt").read_text(encoding="utf-8")
