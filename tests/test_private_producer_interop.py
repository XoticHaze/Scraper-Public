from __future__ import annotations

import base64
import json
import subprocess

from encrypted_compute.transport import decrypt_bytes, generate_recipient, sha256_bytes


def test_node_producer_encrypts_payload_python_consumer_can_decrypt():
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
    payload = json.dumps(
        {
            "recipient": recipient.public,
            "plaintext_b64": base64.b64encode(plaintext).decode("ascii"),
        }
    )
    proc = subprocess.run(
        ["node", "producer_worker/interop.mjs"],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(proc.stdout)
    ciphertext = base64.b64decode(output["ciphertext_b64"])
    root = f"rendezvous/responses/{run_id}/{contract_id}"
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
