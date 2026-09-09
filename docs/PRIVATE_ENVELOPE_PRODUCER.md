# Trusted Private Envelope Producer

Purpose: remove the remaining human-in-the-loop step from encrypted private workloads while keeping routine compute on public GitHub Actions.

## Runtime split

```text
private Scraper repo
  workload allowlist + plaintext private payloads + retained result keys/results
        |
        | trusted Worker reads only an approved workload
        v
Cloudflare Worker (private envelope producer)
        |
        | X25519/HKDF/ChaCha20-Poly1305 envelope bound to exact public run
        v
Scraper-Public rendezvous-exchange
        |
        v
public GitHub Actions runner
        |
        | decrypt in runner temp, fixed contract only
        | execute without GitHub credentials inherited by private process
        | encrypt result to producer-generated result recipient
        v
rendezvous-exchange ciphertext result
        |
        | producer decrypts privately
        v
private Scraper repo producer/results/
```

## Unattended handshake

1. `Encrypted Private Compute` starts on public Actions.
2. The public runner writes `rendezvous/recipients/<run>/request.json` plus its one-run public X25519 recipient to the isolated exchange branch.
3. If repository variable `PRIVATE_ENVELOPE_PRODUCER_URL` is configured, the public runner POSTs only `run_id + contract_id` to the producer. No private data or producer credential is sent by the runner.
4. The producer re-reads the public request/recipient from GitHub and rejects binding mismatches.
5. The producer reads `producer/workloads.json` from the private repo and resolves `workload_id` through that private allowlist. The browser/public runner cannot choose a private path.
6. The producer reads the allowlisted private payload, creates a fresh result X25519 keypair, builds the fixed workload manifest/tar, and encrypts it to the exact public recipient.
7. Ciphertext chunks + envelope are written to `rendezvous-exchange`; the public runner consumes them.
8. The producer stores its result private JWK only in the private repo under `producer/state/<run>/<contract>.json`.
9. On its cron catch-up pass the producer notices the encrypted result, decrypts it privately, and writes the private result archive to `producer/results/<workload>/<run>-<contract>.tar.gz.b64` in the private repo.

The Worker also runs every two minutes as a catch-up mechanism, so a lost HTTP notification does not permanently strand a run.

## Public source, private authority

The producer implementation is intentionally public (`producer_worker/`). Its source contains no secrets and therefore benefits from public CI. Its authority comes only from secrets installed in the trusted Worker runtime and the allowlist/data stored in the private repo.

Required Worker secrets:

- `GITHUB_APP_ID`
- `GITHUB_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY`

The GitHub App should be installed only on `XoticHaze/Scraper` and `XoticHaze/Scraper-Public`, with repository Contents permission sufficient to read/write the rendezvous and private producer state. Narrower split Apps can be used later if desired.

## Deployment

Public compute owns deployment too: `.github/workflows/deploy-private-envelope-producer.yml` runs Wrangler from `Scraper-Public`.

One-time prerequisites:

1. Create/install the narrowly scoped GitHub App and put its three credentials into the Worker as secrets.
2. Add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as Actions secrets in `Scraper-Public` for deployment only.
3. Run `Deploy Private Envelope Producer` once.
4. Set public repository variable `PRIVATE_ENVELOPE_PRODUCER_URL` to the resulting Worker URL.

After that, private jobs are producer-addressable and need no human waiting for recipients.

## Security invariants

- Public `workload_id` is only a request label; the trusted private registry resolves the actual private path.
- A run cannot substitute another run's recipient because the AEAD AAD binds run ID, contract/version, direction, and recipient fingerprint.
- The producer refuses unregistered/disabled workloads.
- Private result keys and decrypted result archives are never written to the public repository.
- Private workload stdout/stderr remains inside the encrypted result capsule.
- The public workflow does not receive the producer's GitHub App credentials.
- The producer endpoint is idempotent: an existing private producer state file prevents duplicate envelope generation for the same run/contract.

## Validation

Public CI includes `tests/test_private_producer_interop.py`, which generates a Python X25519 recipient, encrypts a payload with the Node/Worker producer implementation, and proves the existing Python public consumer decrypts the exact bytes. This cross-runtime test protects the transport contract from implementation drift.
