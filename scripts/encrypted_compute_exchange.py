from __future__ import annotations

"""GitHub exchange helper for public recipients and encrypted ciphertext only.

This process may receive GITHUB_TOKEN in its environment. The decrypted private
workload process never invokes or imports this module and receives a separate,
minimal environment with no GitHub credentials.
"""

import argparse
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from encrypted_compute.transport import sha256_bytes, validate_envelope

API = "https://api.github.com"


def _headers(token: str, *, raw: bool = False) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "repo-app-encrypted-compute-v1",
    }


def _content_url(repo: str, path: str, branch: str | None = None) -> str:
    encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
    url = f"{API}/repos/{repo}/contents/{encoded_path}"
    if branch is not None:
        url += "?ref=" + urllib.parse.quote(branch, safe="")
    return url


def get_raw(repo: str, branch: str, path: str, token: str) -> bytes:
    request = urllib.request.Request(_content_url(repo, path, branch), headers=_headers(token, raw=True))
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def put_file(repo: str, branch: str, path: str, data: bytes, token: str, message: str) -> None:
    body = json.dumps(
        {
            "message": message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": branch,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        _content_url(repo, path),
        data=body,
        method="PUT",
        headers={**_headers(token), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in {200, 201}:
            raise RuntimeError("GitHub exchange write failed")


def token_from_env(name: str) -> str:
    token = os.environ.get(name, "")
    if not token:
        raise RuntimeError("GitHub exchange token missing")
    return token


def cmd_publish_file(args: argparse.Namespace) -> None:
    token = token_from_env(args.token_env)
    put_file(
        args.repo,
        args.branch,
        args.path,
        Path(args.file).read_bytes(),
        token,
        "rendezvous: publish encrypted-compute material",
    )
    print("EXCHANGE_PUBLISH=OK")


def cmd_fetch_workload(args: argparse.Namespace) -> None:
    token = token_from_env(args.token_env)
    envelope_raw = get_raw(args.repo, args.branch, args.envelope_path, token)
    envelope = json.loads(envelope_raw.decode("utf-8"))
    validate_envelope(
        envelope,
        expected_run_id=args.run_id,
        expected_contract_id=args.contract_id,
        expected_contract_version=args.contract_version,
        expected_direction="workload",
        response_root=args.response_root,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "workload-envelope.json").write_bytes(envelope_raw)
    chunk_map: dict[str, str] = {}
    for node in envelope["chunks"]:
        path = str(node["path"])
        body = get_raw(args.repo, args.branch, path, token).decode("ascii").strip()
        if len(body) != int(node["chars"]) or sha256_bytes(body.encode("ascii")) != node["sha256"]:
            raise RuntimeError("GitHub exchange chunk validation failed")
        chunk_map[path] = body
    (out / "chunk-map.json").write_text(json.dumps(chunk_map, sort_keys=True), encoding="utf-8")
    print("EXCHANGE_FETCH=OK")


def cmd_publish_result(args: argparse.Namespace) -> None:
    token = token_from_env(args.token_env)
    staging = Path(args.staging)
    envelope_path = staging / "result-envelope.json"
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    result_root = f"rendezvous/results/{args.run_id}/{args.contract_id}"
    validate_envelope(
        envelope,
        expected_run_id=args.run_id,
        expected_contract_id=args.contract_id,
        expected_contract_version=args.contract_version,
        expected_direction="result",
        response_root=result_root,
    )
    for node in envelope["chunks"]:
        remote = str(node["path"])
        local = staging / "chunks" / Path(remote).name
        body = local.read_text(encoding="ascii").strip()
        if len(body) != int(node["chars"]) or sha256_bytes(body.encode("ascii")) != node["sha256"]:
            raise RuntimeError("result staging chunk validation failed")
        put_file(args.repo, args.branch, remote, body.encode("ascii"), token, "rendezvous: publish encrypted result chunk")
    put_file(
        args.repo,
        args.branch,
        f"{result_root}/result-envelope.json",
        envelope_path.read_bytes(),
        token,
        "rendezvous: publish encrypted result envelope",
    )
    print("EXCHANGE_RESULT_PUBLISH=OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish-file")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--branch", required=True)
    publish.add_argument("--path", required=True)
    publish.add_argument("--file", required=True)
    publish.add_argument("--token-env", default="GH_TOKEN")
    publish.set_defaults(func=cmd_publish_file)

    fetch = sub.add_parser("fetch-workload")
    fetch.add_argument("--repo", required=True)
    fetch.add_argument("--branch", required=True)
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--contract-id", required=True)
    fetch.add_argument("--contract-version", required=True)
    fetch.add_argument("--response-root", required=True)
    fetch.add_argument("--envelope-path", required=True)
    fetch.add_argument("--out", required=True)
    fetch.add_argument("--token-env", default="GH_TOKEN")
    fetch.set_defaults(func=cmd_fetch_workload)

    result = sub.add_parser("publish-result")
    result.add_argument("--repo", required=True)
    result.add_argument("--branch", required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--contract-id", required=True)
    result.add_argument("--contract-version", required=True)
    result.add_argument("--staging", required=True)
    result.add_argument("--token-env", default="GH_TOKEN")
    result.set_defaults(func=cmd_publish_result)

    args = parser.parse_args()
    try:
        args.func(args)
    except urllib.error.HTTPError as exc:
        # Do not print response bodies: they can contain request metadata.
        raise SystemExit(f"GitHub exchange HTTP error {exc.code}") from None


if __name__ == "__main__":
    main()
