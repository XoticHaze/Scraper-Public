from __future__ import annotations

"""Transport-only primitives for encrypted workloads on public compute.

The transport deliberately has no workload execution authority. It binds ciphertext
to a GitHub run, a named contract, a direction, and a one-run recipient key. Fixed
consumers must validate the decrypted workload contract before executing anything.
"""

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SCHEMA = "repo-app-ephemeral-x25519-v1"
AUTHORITY = "private_compute_only"
INFO = b"repo-app-ephemeral-x25519-v1"
DIRECTIONS = {"workload", "result"}
ENVELOPE_FIELDS = {
    "schema",
    "run_id",
    "authority",
    "contract_id",
    "contract_version",
    "direction",
    "recipient_key_id",
    "sender_public_b64",
    "nonce_b64",
    "ciphertext_sha256",
    "plaintext_sha256",
    "chunks",
}
CHUNK_FIELDS = {"path", "sha256", "chars"}


@dataclass(frozen=True)
class Recipient:
    private_b64: str
    public: dict[str, Any]


def b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def b64d(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def key_id(public_raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(public_raw).hexdigest()


def generate_recipient(*, run_id: str, contract_id: str, contract_version: str, direction: str) -> Recipient:
    if direction not in DIRECTIONS:
        raise ValueError("invalid encrypted-compute direction")
    private = x25519.X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    public = {
        "schema": "repo-app-ephemeral-recipient-v1",
        "run_id": str(run_id),
        "authority": AUTHORITY,
        "contract_id": contract_id,
        "contract_version": contract_version,
        "direction": direction,
        "recipient_b64": b64e(public_raw),
        "recipient_key_id": key_id(public_raw),
    }
    return Recipient(private_b64=b64e(private_raw), public=public)


def aad_bytes(
    *,
    run_id: str,
    contract_id: str,
    contract_version: str,
    direction: str,
    recipient_key_id: str,
) -> bytes:
    if direction not in DIRECTIONS:
        raise ValueError("invalid encrypted-compute direction")
    return json.dumps(
        {
            "schema": SCHEMA,
            "run_id": str(run_id),
            "authority": AUTHORITY,
            "contract_id": contract_id,
            "contract_version": contract_version,
            "direction": direction,
            "recipient_key_id": recipient_key_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def derive_key(shared: bytes, aad: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=hashlib.sha256(aad).digest(),
        info=INFO,
    ).derive(shared)


def _validate_key_id(value: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise RuntimeError("recipient key fingerprint invalid")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise RuntimeError("recipient key fingerprint invalid")


def validate_envelope(
    envelope: dict[str, Any],
    *,
    expected_run_id: str,
    expected_contract_id: str,
    expected_contract_version: str,
    expected_direction: str,
    response_root: str,
) -> None:
    if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_FIELDS:
        raise RuntimeError("encrypted-compute envelope field set mismatch")
    if envelope["schema"] != SCHEMA or str(envelope["run_id"]) != str(expected_run_id):
        raise RuntimeError("encrypted-compute envelope run/schema mismatch")
    if envelope["authority"] != AUTHORITY:
        raise RuntimeError("encrypted-compute authority mismatch")
    if envelope["contract_id"] != expected_contract_id or envelope["contract_version"] != expected_contract_version:
        raise RuntimeError("encrypted-compute contract mismatch")
    if envelope["direction"] != expected_direction or expected_direction not in DIRECTIONS:
        raise RuntimeError("encrypted-compute direction mismatch")
    _validate_key_id(str(envelope["recipient_key_id"]))

    chunks = envelope["chunks"]
    if not isinstance(chunks, list) or not chunks or len(chunks) > 128:
        raise RuntimeError("encrypted-compute chunk list invalid")
    prefix = response_root.rstrip("/") + "/"
    seen: set[str] = set()
    total_chars = 0
    for node in chunks:
        if not isinstance(node, dict) or set(node) != CHUNK_FIELDS:
            raise RuntimeError("encrypted-compute chunk descriptor mismatch")
        path = str(node["path"])
        if not path.startswith(prefix) or ".." in Path(path).parts or path in seen:
            raise RuntimeError("encrypted-compute chunk path invalid")
        seen.add(path)
        digest = str(node["sha256"])
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RuntimeError("encrypted-compute chunk digest invalid")
        chars = int(node["chars"])
        if chars <= 0 or chars > 900_000:
            raise RuntimeError("encrypted-compute chunk size invalid")
        total_chars += chars
    if total_chars > 60_000_000:
        raise RuntimeError("encrypted-compute payload exceeds transport cap")


def encrypt_bytes(
    plaintext: bytes,
    *,
    recipient_public_b64: str,
    run_id: str,
    contract_id: str,
    contract_version: str,
    direction: str,
) -> tuple[bytes, dict[str, Any]]:
    recipient_raw = b64d(recipient_public_b64)
    if len(recipient_raw) != 32:
        raise RuntimeError("recipient public key length invalid")
    recipient_id = key_id(recipient_raw)
    sender = x25519.X25519PrivateKey.generate()
    sender_public_raw = sender.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    aad = aad_bytes(
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        direction=direction,
        recipient_key_id=recipient_id,
    )
    shared = sender.exchange(x25519.X25519PublicKey.from_public_bytes(recipient_raw))
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(derive_key(shared, aad)).encrypt(nonce, plaintext, aad)
    meta = {
        "schema": SCHEMA,
        "run_id": str(run_id),
        "authority": AUTHORITY,
        "contract_id": contract_id,
        "contract_version": contract_version,
        "direction": direction,
        "recipient_key_id": recipient_id,
        "sender_public_b64": b64e(sender_public_raw),
        "nonce_b64": b64e(nonce),
        "ciphertext_sha256": sha256_bytes(ciphertext),
        "plaintext_sha256": sha256_bytes(plaintext),
    }
    return ciphertext, meta


def decrypt_bytes(
    *,
    envelope: dict[str, Any],
    ciphertext: bytes,
    private_key_b64: str,
    expected_run_id: str,
    expected_contract_id: str,
    expected_contract_version: str,
    expected_direction: str,
    response_root: str,
) -> bytes:
    validate_envelope(
        envelope,
        expected_run_id=expected_run_id,
        expected_contract_id=expected_contract_id,
        expected_contract_version=expected_contract_version,
        expected_direction=expected_direction,
        response_root=response_root,
    )
    if sha256_bytes(ciphertext) != envelope["ciphertext_sha256"]:
        raise RuntimeError("assembled ciphertext digest mismatch")

    private_raw = b64d(private_key_b64.strip())
    if len(private_raw) != 32:
        raise RuntimeError("recipient private key length invalid")
    private = x25519.X25519PrivateKey.from_private_bytes(private_raw)
    recipient_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    recipient_id = key_id(recipient_raw)
    if recipient_id != envelope["recipient_key_id"]:
        raise RuntimeError("recipient key fingerprint mismatch")

    sender_raw = b64d(str(envelope["sender_public_b64"]))
    nonce = b64d(str(envelope["nonce_b64"]))
    if len(sender_raw) != 32 or len(nonce) != 12:
        raise RuntimeError("sender key/nonce length invalid")
    aad = aad_bytes(
        run_id=expected_run_id,
        contract_id=expected_contract_id,
        contract_version=expected_contract_version,
        direction=expected_direction,
        recipient_key_id=recipient_id,
    )
    shared = private.exchange(x25519.X25519PublicKey.from_public_bytes(sender_raw))
    plaintext = ChaCha20Poly1305(derive_key(shared, aad)).decrypt(nonce, ciphertext, aad)
    if sha256_bytes(plaintext) != envelope["plaintext_sha256"]:
        raise RuntimeError("decrypted plaintext digest mismatch")
    return plaintext


def split_ciphertext(
    ciphertext: bytes,
    *,
    root: str,
    chunk_chars: int = 700_000,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    if chunk_chars <= 0 or chunk_chars > 900_000:
        raise ValueError("invalid chunk size")
    encoded = b64e(ciphertext)
    files: list[tuple[str, str]] = []
    nodes: list[dict[str, Any]] = []
    for index, start in enumerate(range(0, len(encoded), chunk_chars)):
        body = encoded[start : start + chunk_chars]
        path = f"{root.rstrip('/')}/chunk-{index:04d}.b64"
        files.append((path, body))
        nodes.append({"path": path, "sha256": sha256_bytes(body.encode("ascii")), "chars": len(body)})
    if not files:
        raise RuntimeError("cannot split empty ciphertext")
    return files, nodes


def assemble_chunks(envelope: dict[str, Any], chunks: dict[str, str]) -> bytes:
    pieces: list[str] = []
    for node in envelope["chunks"]:
        path = str(node["path"])
        if path not in chunks:
            raise RuntimeError(f"missing encrypted-compute chunk: {path}")
        body = chunks[path].strip()
        if len(body) != int(node["chars"]):
            raise RuntimeError(f"chunk length mismatch: {path}")
        if sha256_bytes(body.encode("ascii")) != node["sha256"]:
            raise RuntimeError(f"chunk digest mismatch: {path}")
        pieces.append(body)
    return b64d("".join(pieces))
