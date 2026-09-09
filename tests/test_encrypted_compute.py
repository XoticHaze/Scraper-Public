from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from encrypted_compute.client import decrypt_result, prepare_workload, safe_extract_result
from encrypted_compute.transport import (
    decrypt_bytes,
    encrypt_bytes,
    generate_recipient,
    split_ciphertext,
)
from scripts.encrypted_compute_consumer import consume


CONTRACT_ID = "python-bundle-v1"
CONTRACT_VERSION = "1"
RUN_ID = "424242"


def test_transport_is_bound_to_run_and_contract() -> None:
    recipient = generate_recipient(
        run_id=RUN_ID,
        contract_id=CONTRACT_ID,
        contract_version=CONTRACT_VERSION,
        direction="workload",
    )
    plaintext = b"private-payload"
    ciphertext, meta = encrypt_bytes(
        plaintext,
        recipient_public_b64=recipient.public["recipient_b64"],
        run_id=RUN_ID,
        contract_id=CONTRACT_ID,
        contract_version=CONTRACT_VERSION,
        direction="workload",
    )
    root = f"rendezvous/responses/{RUN_ID}/{CONTRACT_ID}"
    _, nodes = split_ciphertext(ciphertext, root=root, chunk_chars=20)
    envelope = {**meta, "chunks": nodes}

    recovered = decrypt_bytes(
        envelope=envelope,
        ciphertext=ciphertext,
        private_key_b64=recipient.private_b64,
        expected_run_id=RUN_ID,
        expected_contract_id=CONTRACT_ID,
        expected_contract_version=CONTRACT_VERSION,
        expected_direction="workload",
        response_root=root,
    )
    assert recovered == plaintext

    with pytest.raises(RuntimeError, match="run/schema"):
        decrypt_bytes(
            envelope=envelope,
            ciphertext=ciphertext,
            private_key_b64=recipient.private_b64,
            expected_run_id="wrong-run",
            expected_contract_id=CONTRACT_ID,
            expected_contract_version=CONTRACT_VERSION,
            expected_direction="workload",
            response_root=root,
        )


def test_private_workload_round_trip_does_not_inherit_github_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload_dir = tmp_path / "private-payload"
    payload_dir.mkdir()
    (payload_dir / "entrypoint.py").write_text(
        """from pathlib import Path
import json, os
out = Path(os.environ['REPO_APP_PRIVATE_OUTPUT'])
out.mkdir(parents=True, exist_ok=True)
print('PRIVATE_STDOUT_MARKER')
print('PRIVATE_STDERR_MARKER', file=__import__('sys').stderr)
(out / 'answer.json').write_text(json.dumps({
    'value': 42,
    'github_token_seen': os.environ.get('GITHUB_TOKEN'),
    'github_run_id_seen': os.environ.get('GITHUB_RUN_ID'),
}), encoding='utf-8')
""",
        encoding="utf-8",
    )

    runner_recipient = generate_recipient(
        run_id=RUN_ID,
        contract_id=CONTRACT_ID,
        contract_version=CONTRACT_VERSION,
        direction="workload",
    )
    response_root = f"rendezvous/responses/{RUN_ID}/{CONTRACT_ID}"
    prepared = prepare_workload(
        recipient=runner_recipient.public,
        payload_dir=payload_dir,
        entrypoint="entrypoint.py",
        response_root=response_root,
    )

    envelope_path = tmp_path / "workload-envelope.json"
    envelope_path.write_text(json.dumps(prepared["envelope"]), encoding="utf-8")
    chunk_map = {path: body for path, body in prepared["chunk_files"]}
    chunk_map_path = tmp_path / "chunk-map.json"
    chunk_map_path.write_text(json.dumps(chunk_map), encoding="utf-8")
    private_key_path = tmp_path / "runner-private.b64"
    private_key_path.write_text(runner_recipient.private_b64, encoding="ascii")
    result_staging = tmp_path / "result-staging"

    # Prove that parent-runner secrets are stripped instead of merely absent in test.
    monkeypatch.setenv("GITHUB_TOKEN", "PARENT_SECRET_MUST_NOT_LEAK")
    monkeypatch.setenv("GITHUB_RUN_ID", RUN_ID)

    args = SimpleNamespace(
        registry="config/encrypted_compute_contracts.json",
        contract_id=CONTRACT_ID,
        contract_version=CONTRACT_VERSION,
        run_id=RUN_ID,
        envelope=str(envelope_path),
        chunk_map=str(chunk_map_path),
        private_key=str(private_key_path),
        response_root=response_root,
        result_staging=str(result_staging),
    )
    receipt = consume(args)
    assert receipt["status"] == "PASS"
    assert receipt["github_credentials_exposed_to_workload"] is False
    assert "PRIVATE_STDOUT_MARKER" not in json.dumps(receipt)
    assert "PARENT_SECRET_MUST_NOT_LEAK" not in json.dumps(receipt)

    result_envelope = json.loads((result_staging / "result-envelope.json").read_text(encoding="utf-8"))
    result_chunks = {
        str(node["path"]): (result_staging / "chunks" / Path(str(node["path"])).name).read_text(encoding="ascii")
        for node in result_envelope["chunks"]
    }
    result_root = f"rendezvous/results/{RUN_ID}/{CONTRACT_ID}"
    result_tar = decrypt_result(
        envelope=result_envelope,
        chunks=result_chunks,
        result_private_key_b64=prepared["result_private_key_b64"],
        run_id=RUN_ID,
        contract_id=CONTRACT_ID,
        contract_version=CONTRACT_VERSION,
        result_root=result_root,
    )
    extracted = tmp_path / "decrypted-result"
    safe_extract_result(result_tar, extracted)

    answer = json.loads((extracted / "output" / "answer.json").read_text(encoding="utf-8"))
    assert answer == {"value": 42, "github_token_seen": None, "github_run_id_seen": None}
    assert "PRIVATE_STDOUT_MARKER" in (extracted / "execution" / "stdout.txt").read_text(encoding="utf-8")
    assert "PRIVATE_STDERR_MARKER" in (extracted / "execution" / "stderr.txt").read_text(encoding="utf-8")


def test_result_private_key_cannot_decrypt_workload(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payload"
    payload_dir.mkdir()
    (payload_dir / "entrypoint.py").write_text("pass\n", encoding="utf-8")
    runner_recipient = generate_recipient(
        run_id=RUN_ID,
        contract_id=CONTRACT_ID,
        contract_version=CONTRACT_VERSION,
        direction="workload",
    )
    response_root = f"rendezvous/responses/{RUN_ID}/{CONTRACT_ID}"
    prepared = prepare_workload(
        recipient=runner_recipient.public,
        payload_dir=payload_dir,
        entrypoint="entrypoint.py",
        response_root=response_root,
    )
    envelope = prepared["envelope"]
    import base64

    ciphertext = base64.b64decode("".join(body for _, body in prepared["chunk_files"]))
    with pytest.raises(Exception):
        decrypt_bytes(
            envelope=envelope,
            ciphertext=ciphertext,
            private_key_b64=prepared["result_private_key_b64"],
            expected_run_id=RUN_ID,
            expected_contract_id=CONTRACT_ID,
            expected_contract_version=CONTRACT_VERSION,
            expected_direction="workload",
            response_root=response_root,
        )
