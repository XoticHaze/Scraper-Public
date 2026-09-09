from __future__ import annotations

"""Private-side packaging helpers for the public encrypted-compute transport.

This code is safe to publish: it contains no credential or private material. The
caller must keep payload plaintext and generated result private keys on the private
side and upload only the returned encrypted exchange files.
"""

import io
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from encrypted_compute.transport import (
    assemble_chunks,
    decrypt_bytes,
    encrypt_bytes,
    generate_recipient,
    key_id,
    b64d,
    sha256_bytes,
    split_ciphertext,
)

WORKLOAD_SCHEMA = "repo-app-private-workload-v1"


def _safe_rel(value: str) -> PurePosixPath:
    rel = PurePosixPath(value)
    if not value or rel.is_absolute() or ".." in rel.parts or rel.parts[0] in {".git", ".github"}:
        raise RuntimeError("unsafe private payload path")
    return rel


def _sha256_path(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def collect_payload_files(payload_dir: Path) -> dict[str, Path]:
    if not payload_dir.is_dir():
        raise RuntimeError("private payload directory missing")
    files: dict[str, Path] = {}
    for path in sorted(payload_dir.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("private payload contains symlink")
        if not path.is_file():
            continue
        rel = path.relative_to(payload_dir).as_posix()
        _safe_rel(rel)
        if rel == "workload-manifest.json":
            raise RuntimeError("workload-manifest.json is reserved")
        files[rel] = path
    if not files:
        raise RuntimeError("private payload is empty")
    return files


def build_workload_tar(
    *,
    payload_dir: Path,
    contract_id: str,
    contract_version: str,
    entrypoint: str,
    result_recipient_b64: str,
    result_recipient_key_id: str,
) -> bytes:
    files = collect_payload_files(payload_dir)
    if entrypoint not in files:
        raise RuntimeError("private payload entrypoint missing")
    manifest = {
        "schema": WORKLOAD_SCHEMA,
        "contract_id": contract_id,
        "contract_version": str(contract_version),
        "entrypoint": entrypoint,
        "files": {rel: _sha256_path(path) for rel, path in files.items()},
        "result_recipient_b64": result_recipient_b64,
        "result_recipient_key_id": result_recipient_key_id,
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for rel, path in files.items():
            info = archive.gettarinfo(str(path), arcname=rel)
            with path.open("rb") as handle:
                archive.addfile(info, handle)
        encoded = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
        info = tarfile.TarInfo("workload-manifest.json")
        info.size = len(encoded)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(encoded))
    return buffer.getvalue()


def prepare_workload(
    *,
    recipient: dict[str, Any],
    payload_dir: Path,
    entrypoint: str,
    response_root: str,
) -> dict[str, Any]:
    required_recipient = {
        "schema",
        "run_id",
        "authority",
        "contract_id",
        "contract_version",
        "direction",
        "recipient_b64",
        "recipient_key_id",
    }
    if set(recipient) != required_recipient or recipient.get("schema") != "repo-app-ephemeral-recipient-v1":
        raise RuntimeError("runner recipient schema/fields invalid")
    if recipient.get("direction") != "workload":
        raise RuntimeError("runner recipient direction invalid")
    recipient_raw = b64d(str(recipient["recipient_b64"]))
    if len(recipient_raw) != 32 or key_id(recipient_raw) != recipient["recipient_key_id"]:
        raise RuntimeError("runner recipient fingerprint mismatch")

    result_recipient = generate_recipient(
        run_id=str(recipient["run_id"]),
        contract_id=str(recipient["contract_id"]),
        contract_version=str(recipient["contract_version"]),
        direction="result",
    )
    result_public = result_recipient.public
    payload = build_workload_tar(
        payload_dir=payload_dir,
        contract_id=str(recipient["contract_id"]),
        contract_version=str(recipient["contract_version"]),
        entrypoint=entrypoint,
        result_recipient_b64=str(result_public["recipient_b64"]),
        result_recipient_key_id=str(result_public["recipient_key_id"]),
    )
    ciphertext, meta = encrypt_bytes(
        payload,
        recipient_public_b64=str(recipient["recipient_b64"]),
        run_id=str(recipient["run_id"]),
        contract_id=str(recipient["contract_id"]),
        contract_version=str(recipient["contract_version"]),
        direction="workload",
    )
    chunk_files, chunk_nodes = split_ciphertext(ciphertext, root=response_root)
    envelope = {**meta, "chunks": chunk_nodes}
    return {
        "envelope": envelope,
        "chunk_files": chunk_files,
        "result_private_key_b64": result_recipient.private_b64,
        "result_recipient": result_public,
        "workload_plaintext_sha256": sha256_bytes(payload),
    }


def decrypt_result(
    *,
    envelope: dict[str, Any],
    chunks: dict[str, str],
    result_private_key_b64: str,
    run_id: str,
    contract_id: str,
    contract_version: str,
    result_root: str,
) -> bytes:
    ciphertext = assemble_chunks(envelope, chunks)
    return decrypt_bytes(
        envelope=envelope,
        ciphertext=ciphertext,
        private_key_b64=result_private_key_b64,
        expected_run_id=run_id,
        expected_contract_id=contract_id,
        expected_contract_version=contract_version,
        expected_direction="result",
        response_root=result_root,
    )


def safe_extract_result(result_tar_gz: bytes, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(result_tar_gz), mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 256:
            raise RuntimeError("private result archive too large")
        for member in members:
            rel = _safe_rel(member.name)
            if not member.isfile():
                raise RuntimeError("private result contains non-file member")
            target = output_dir.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("private result member unreadable")
            target.write_bytes(source.read())
