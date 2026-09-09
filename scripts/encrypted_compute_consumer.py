from __future__ import annotations

"""Fail-closed consumer for private code/data on public GitHub compute.

The public workflow owns transport and a fixed execution contract only. Decrypted
payloads live in a temporary directory, private stdout/stderr never reach Actions
logs, and result material is encrypted to a private-side result recipient before it
leaves the runner.
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from encrypted_compute.transport import (
    assemble_chunks,
    decrypt_bytes,
    encrypt_bytes,
    sha256_bytes,
    split_ciphertext,
)

MANIFEST_SCHEMA = "repo-app-private-workload-v1"
RESULT_SCHEMA = "repo-app-private-result-v1"


def sha256_path(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_contract(registry_path: Path, contract_id: str, contract_version: str) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema") != "repo-app-encrypted-compute-contracts-v1":
        raise RuntimeError("encrypted-compute registry schema mismatch")
    contract = (registry.get("contracts") or {}).get(contract_id)
    if not isinstance(contract, dict):
        raise RuntimeError("encrypted-compute contract not registered")
    if str(contract.get("version")) != str(contract_version):
        raise RuntimeError("encrypted-compute contract version mismatch")
    return contract


def safe_relpath(value: str) -> PurePosixPath:
    rel = PurePosixPath(value)
    if not value or rel.is_absolute() or ".." in rel.parts:
        raise RuntimeError("unsafe private workload path")
    if rel.parts[0] in {".git", ".github"}:
        raise RuntimeError("reserved private workload path")
    return rel


def inspect_archive(payload: bytes, contract: dict[str, Any]) -> tuple[list[tarfile.TarInfo], int]:
    max_files = int(contract["max_files"])
    max_bytes = int(contract["max_plaintext_bytes"])
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > max_files + 1:
            raise RuntimeError("private workload archive file count invalid")
        total = 0
        for member in members:
            safe_relpath(member.name)
            if not member.isfile():
                raise RuntimeError("private workload archive contains non-file member")
            if member.size < 0 or member.size > max_bytes:
                raise RuntimeError("private workload member exceeds size cap")
            total += member.size
            if total > max_bytes:
                raise RuntimeError("private workload exceeds plaintext size cap")
        return members, total


def extract_and_validate(payload: bytes, root: Path, contract_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    members, _ = inspect_archive(payload, contract)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in members:
            rel = safe_relpath(member.name)
            target = root.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("private workload member unreadable")
            with target.open("wb") as handle:
                shutil.copyfileobj(source, handle)

    manifest_path = root / "workload-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("private workload manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema",
        "contract_id",
        "contract_version",
        "entrypoint",
        "files",
        "result_recipient_b64",
        "result_recipient_key_id",
    }
    if set(manifest) != required:
        raise RuntimeError("private workload manifest field set mismatch")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise RuntimeError("private workload manifest schema mismatch")
    if manifest["contract_id"] != contract_id or str(manifest["contract_version"]) != str(contract["version"]):
        raise RuntimeError("private workload manifest contract mismatch")
    if manifest["entrypoint"] != contract["entrypoint"]:
        raise RuntimeError("private workload entrypoint mismatch")

    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise RuntimeError("private workload manifest files invalid")
    archive_files = {member.name for member in members} - {"workload-manifest.json"}
    if set(files) != archive_files:
        raise RuntimeError("private workload manifest/archive file set mismatch")
    if contract["entrypoint"] not in files:
        raise RuntimeError("private workload entrypoint not admitted")
    for rel, digest in files.items():
        safe_relpath(rel)
        if not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeError("private workload digest invalid")
        if sha256_path(root / rel) != digest:
            raise RuntimeError(f"private workload inner digest mismatch: {rel}")

    # Validate the private-side result recipient without disclosing it publicly.
    from encrypted_compute.transport import b64d, key_id

    result_raw = b64d(str(manifest["result_recipient_b64"]))
    if len(result_raw) != 32 or key_id(result_raw) != manifest["result_recipient_key_id"]:
        raise RuntimeError("private result recipient mismatch")
    return manifest


def minimal_env(work_root: Path) -> dict[str, str]:
    # Deliberately do not inherit GITHUB_*, ACTIONS_*, tokens, cookies, secrets, or
    # arbitrary repository environment. PATH is required to invoke the interpreter.
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(work_root / ".home"),
        "TMPDIR": str(work_root / ".tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "REPO_APP_PRIVATE_OUTPUT": str(work_root / "private_output"),
    }
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    return env


def collect_result_files(root: Path, contract: dict[str, Any]) -> list[Path]:
    output_root = root / str(contract["output_root"])
    if not output_root.exists():
        return []
    files: list[Path] = []
    total = 0
    for path in sorted(output_root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("private result contains symlink")
        if not path.is_file():
            continue
        rel = path.relative_to(output_root).as_posix()
        safe_relpath(rel)
        size = path.stat().st_size
        total += size
        files.append(path)
        if len(files) > int(contract["max_result_files"]) or total > int(contract["max_result_bytes"]):
            raise RuntimeError("private result exceeds contract cap")
    return files


def build_result_tar(
    *,
    root: Path,
    contract_id: str,
    contract_version: str,
    return_code: int,
    timed_out: bool,
    duration_seconds: float,
    stdout_path: Path,
    stderr_path: Path,
    contract: dict[str, Any],
) -> tuple[bytes, int, int]:
    output_files = collect_result_files(root, contract)
    metadata = {
        "schema": RESULT_SCHEMA,
        "contract_id": contract_id,
        "contract_version": contract_version,
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": round(duration_seconds, 3),
        "output_file_count": len(output_files),
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, path in (
            ("execution/stdout.txt", stdout_path),
            ("execution/stderr.txt", stderr_path),
        ):
            info = archive.gettarinfo(str(path), arcname=name)
            with path.open("rb") as handle:
                archive.addfile(info, handle)
        encoded = (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8")
        info = tarfile.TarInfo("execution/result.json")
        info.size = len(encoded)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(encoded))
        output_root = root / str(contract["output_root"])
        for path in output_files:
            rel = path.relative_to(output_root).as_posix()
            info = archive.gettarinfo(str(path), arcname=f"output/{rel}")
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    result = buffer.getvalue()
    if len(result) > int(contract["max_result_bytes"]) + 5_000_000:
        raise RuntimeError("encrypted result archive exceeds cap")
    return result, len(output_files), sum(path.stat().st_size for path in output_files)


def write_result_transport(
    *,
    result_plaintext: bytes,
    result_recipient_b64: str,
    run_id: str,
    contract_id: str,
    contract_version: str,
    result_root: str,
    staging_dir: Path,
) -> tuple[dict[str, Any], int]:
    ciphertext, meta = encrypt_bytes(
        result_plaintext,
        recipient_public_b64=result_recipient_b64,
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        direction="result",
    )
    files, chunk_nodes = split_ciphertext(ciphertext, root=result_root)
    envelope = {**meta, "chunks": chunk_nodes}
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "result-envelope.json").write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    chunks_dir = staging_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for path, body in files:
        filename = Path(path).name
        (chunks_dir / filename).write_text(body, encoding="ascii")
    return envelope, len(files)


def consume(args: argparse.Namespace) -> dict[str, Any]:
    contract = load_contract(Path(args.registry), args.contract_id, args.contract_version)
    envelope = json.loads(Path(args.envelope).read_text(encoding="utf-8"))
    chunk_map = json.loads(Path(args.chunk_map).read_text(encoding="utf-8"))
    if not isinstance(chunk_map, dict):
        raise RuntimeError("encrypted-compute chunk map invalid")
    ciphertext = assemble_chunks(envelope, {str(k): str(v) for k, v in chunk_map.items()})
    private_key_b64 = Path(args.private_key).read_text(encoding="ascii").strip()
    plaintext = decrypt_bytes(
        envelope=envelope,
        ciphertext=ciphertext,
        private_key_b64=private_key_b64,
        expected_run_id=args.run_id,
        expected_contract_id=args.contract_id,
        expected_contract_version=args.contract_version,
        expected_direction="workload",
        response_root=args.response_root,
    )

    with tempfile.TemporaryDirectory(prefix="repo-app-private-") as temp_dir:
        root = Path(temp_dir)
        manifest = extract_and_validate(plaintext, root, args.contract_id, contract)
        stdout_path = root / ".private-stdout"
        stderr_path = root / ".private-stderr"
        start = time.monotonic()
        timed_out = False
        return_code = 125
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            try:
                completed = subprocess.run(
                    [sys.executable, "-B", str(contract["entrypoint"])],
                    cwd=root,
                    env=minimal_env(root),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout=int(contract["timeout_seconds"]),
                    check=False,
                )
                return_code = int(completed.returncode)
            except subprocess.TimeoutExpired:
                timed_out = True
                return_code = 124
        duration = time.monotonic() - start

        result_plaintext, output_count, output_bytes = build_result_tar(
            root=root,
            contract_id=args.contract_id,
            contract_version=args.contract_version,
            return_code=return_code,
            timed_out=timed_out,
            duration_seconds=duration,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            contract=contract,
        )
        result_root = f"rendezvous/results/{args.run_id}/{args.contract_id}"
        result_envelope, chunk_count = write_result_transport(
            result_plaintext=result_plaintext,
            result_recipient_b64=str(manifest["result_recipient_b64"]),
            run_id=args.run_id,
            contract_id=args.contract_id,
            contract_version=args.contract_version,
            result_root=result_root,
            staging_dir=Path(args.result_staging),
        )

    return {
        "schema": "repo-app-encrypted-compute-receipt-v1",
        "contract_id": args.contract_id,
        "contract_version": args.contract_version,
        "run_id": str(args.run_id),
        "status": "PASS" if return_code == 0 and not timed_out else "FAIL",
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 3),
        "workload_plaintext_sha256": sha256_bytes(plaintext),
        "result_ciphertext_sha256": result_envelope["ciphertext_sha256"],
        "result_chunk_count": chunk_count,
        "private_output_file_count": output_count,
        "private_output_bytes": output_bytes,
        "private_plaintext_emitted": False,
        "stdout_stderr_public": False,
        "github_credentials_exposed_to_workload": False,
        "network_isolation": False,
    }


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
    args = parser.parse_args()
    receipt = consume(args)
    print("ENCRYPTED_COMPUTE_RECEIPT=" + json.dumps(receipt, sort_keys=True))
    raise SystemExit(0 if receipt["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
