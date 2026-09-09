# Encrypted Public Compute

## Purpose

Use public GitHub Actions compute for private repository workloads without publishing private code, data, credentials, stdout/stderr, or results in plaintext.

`Scraper-Public` is the execution/exchange plane. A private repository or trusted private-side agent remains the plaintext authority.

## Security model

The design borrows the proven Foundry public-compute rendezvous pattern:

- X25519 one-run recipient generated inside the public runner;
- HKDF-SHA256 key derivation;
- ChaCha20-Poly1305 authenticated encryption;
- associated data bound to run and execution authority;
- isolated exchange branch;
- fail-closed payload admission;
- transient runner private keys and decrypted workspaces;
- sanitized public receipts only.

This implementation generalizes that pattern for repo applications and adds encrypted return results.

### Authenticated binding

Every encrypted envelope is bound to:

- schema;
- GitHub `run_id`;
- authority `private_compute_only`;
- fixed `contract_id`;
- fixed `contract_version`;
- direction: `workload` or `result`;
- exact recipient public-key fingerprint.

A payload encrypted for one run, contract, direction, or recipient cannot be replayed as another valid workload.

## Components

- `encrypted_compute/transport.py` — transport-only X25519/HKDF/AEAD/chunk primitives; owns no execution authority.
- `encrypted_compute/client.py` — private-side packaging and result decryption helpers.
- `tools/private_compute_client.py` — CLI for preparing encrypted workloads and decrypting results.
- `config/encrypted_compute_contracts.json` — allowlisted public execution contracts.
- `scripts/encrypted_compute_consumer.py` — fail-closed fixed-contract consumer.
- `scripts/encrypted_compute_exchange.py` — GitHub exchange helper; handles only public recipients and ciphertext.
- `scripts/encrypted_compute_run.py` — sanitized execution wrapper.
- `.github/workflows/encrypted-private-compute.yml` — public compute rendezvous workflow.

## Current fixed contract

`python-bundle-v1`, version `1`:

- fixed entrypoint: `entrypoint.py`;
- max files: 256;
- plaintext cap: 25 MB;
- result-file cap: 128;
- result-data cap: 15 MB;
- execution timeout: 600 seconds;
- declared output root: `private_output`.

This is intentionally not an arbitrary command contract.

## Execution isolation

The public workflow itself has GitHub repository credentials so it can publish/fetch encrypted exchange material. The decrypted private workload is launched as a child process with an explicit minimal environment instead of inheriting the runner environment.

The private process receives only:

- `PATH`;
- temporary `HOME` and `TMPDIR`;
- locale/Python execution settings;
- `REPO_APP_PRIVATE_OUTPUT`.

It does **not** receive `GITHUB_TOKEN`, `GITHUB_RUN_ID`, other `GITHUB_*`/`ACTIONS_*` state, repository credentials, MAC.BID credentials, or arbitrary parent environment variables.

Network egress is currently available (`network_isolation: false`). The security boundary therefore relies on not giving the private process public-runner secrets; stronger network isolation can be added later for contracts that require it.

## Lifecycle

```text
1. Start public encrypted-compute run.
2. Runner creates one-run X25519 workload keypair.
3. Runner publishes only recipient public key + fingerprint on rendezvous-exchange.
4. Trusted private side reads recipient.
5. Private side generates a separate result-recipient keypair.
6. Private side packages private code/data with exact file digests.
7. Private side encrypts workload to the runner recipient and publishes ciphertext only.
8. Runner validates envelope/chunks, decrypts in temporary storage, validates contract + file set + digests.
9. Private entrypoint runs with stripped environment; stdout/stderr stay private.
10. Runner packages stdout/stderr + declared private outputs.
11. Runner encrypts result to the private-side result recipient.
12. Runner publishes ciphertext result + sanitized receipt.
13. Runner removes one-run private key, encrypted request staging, decrypted workspace/result staging, and receipt temp files.
14. Private side fetches ciphertext and decrypts with its retained result private key.
```

## Exchange paths

Isolated branch: `rendezvous-exchange`

```text
rendezvous/recipients/<run_id>/<contract_id>.json
rendezvous/responses/<run_id>/<contract_id>/workload-envelope.json
rendezvous/responses/<run_id>/<contract_id>/chunk-*.b64
rendezvous/results/<run_id>/<contract_id>/result-envelope.json
rendezvous/results/<run_id>/<contract_id>/chunk-*.b64
```

Only public recipient material, authenticated ciphertext, and sanitized receipts belong on the public exchange.

## Live proof — 2026-09-09

A real public GitHub Actions run completed successfully:

- workflow run: `34321562721`;
- contract: `python-bundle-v1` / version `1`;
- one-run workload recipient fingerprint: `sha256:d410662a626a0f1b5cfcae217c4b31ba8aa3a7856f8efc977e58f2d0d91c2686`;
- separate private result-recipient fingerprint: `sha256:32e356f64f66f17f23a8064aeaeb0c00e80c5245c7f7ba275d68550926827246`;
- public receipt status: `PASS`;
- private output files: 1;
- public `stdout_stderr_public`: `false`;
- public `private_plaintext_emitted`: `false`;
- public `github_credentials_exposed_to_workload`: `false`.

The test workload deliberately printed unique markers to stdout and stderr. Full public Actions logs were inspected and contained neither marker.

The returned encrypted result was then decrypted off-repo with the retained result private key. It contained the private stdout/stderr and this output state:

```json
{
  "round_trip": "ok",
  "value": 73,
  "github_token_seen": null,
  "github_run_id_seen": null
}
```

This proves the live chain:

**one-run recipient → encrypted workload → public compute → encrypted private result → private-side decryption**.

## Private-side CLI shape

After a run publishes its one-run recipient:

```bash
python tools/private_compute_client.py prepare \
  --recipient recipient.json \
  --payload-dir ./private-payload \
  --entrypoint entrypoint.py \
  --out ./prepared
```

Upload only files under `prepared/upload/` to the exact run-bound response path. Never upload `prepared/PRIVATE_DO_NOT_UPLOAD/`; it contains the result private key/state needed to decrypt the return capsule.

After the runner publishes the encrypted result:

```bash
python tools/private_compute_client.py decrypt-result \
  --state prepared/PRIVATE_DO_NOT_UPLOAD/state.json \
  --private-key prepared/PRIVATE_DO_NOT_UPLOAD/result-private-key.b64 \
  --envelope result-envelope.json \
  --chunks-dir result-chunks \
  --out ./private-result
```

## Adding another private workload

Do not broaden `python-bundle-v1` merely because another project needs compute. Prefer a new explicitly registered contract when execution rules, dependencies, outputs, timeout, authority, or threat model differ.

For each new contract define:

- fixed identity/version;
- fixed entrypoint/harness;
- file and size limits;
- allowed dependencies/runtime;
- execution timeout;
- output contract;
- whether network access is permitted;
- sanitized public receipt fields.

Transport remains reusable; execution authority remains narrow.
