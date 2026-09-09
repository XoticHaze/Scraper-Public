# Trusted private envelope producer — one-time setup

The producer is intentionally a tiny trusted control service. It does not run private workloads itself. It only validates an attested public-compute run, reads an allowlisted private workload, encrypts it to that run's one-time X25519 recipient, and later decrypts/stores the encrypted result in the private repository.

The producer is cron-only. It exposes no public endpoint that can select a private path or trigger a workload.

## 1. Create a narrowly scoped GitHub App

From GitHub account settings:

1. Open **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Use a name such as `Repo App Private Envelope Producer`.
3. A normal repository/homepage URL is sufficient. Disable webhooks; the producer uses polling/cron and does not require a webhook.
4. Grant only these repository permissions:
   - **Contents: Read and write**
   - **Actions: Read-only**
5. Do not grant Administration, Workflows, Issues, Pull requests, Members, Secrets, or unrelated permissions.
6. Install the App on **Only select repositories**:
   - `XoticHaze/Scraper`
   - `XoticHaze/Scraper-Public`
7. Generate one GitHub App private key.
8. Record:
   - App ID
   - Installation ID
   - private key PEM

The Actions-read permission is required because the producer independently queries GitHub's workflow-run metadata and refuses to release a private workload unless the run references the exact trusted reusable-workflow SHA recorded in the private registry.

## 2. Create a narrow Cloudflare deployment token

Create a Cloudflare API token scoped to the account that will host the Worker.

Required capability for this Worker deployment is **Workers Scripts: Edit/Write** on that account. The Worker uses a Cron Trigger, which is managed with the Worker script deployment. Avoid broad account/zone permissions that are not needed.

Record the Cloudflare Account ID.

## 3. Add only the Cloudflare deployment credentials to Scraper-Public Actions

In `XoticHaze/Scraper-Public → Settings → Secrets and variables → Actions`, create repository secrets:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

Do **not** put the GitHub App private key into the public repository or Pages source. The public deployment workflow needs Cloudflare deployment authority only.

## 4. Deploy the Worker using public GitHub compute

Run the public workflow:

`Deploy Private Envelope Producer`

It executes `wrangler deploy` against `producer_worker/wrangler.jsonc` and installs the `*/2 * * * *` Cron Trigger.

The Worker name is:

`scraper-private-envelope-producer`

## 5. Bind GitHub App credentials directly in Cloudflare

After the first Worker deployment, open the Worker in the Cloudflare dashboard and add these Worker secrets/variables directly there:

- `GITHUB_APP_ID`
- `GITHUB_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY`

The PEM must retain its normal multiline private-key form.

These values belong to the trusted producer environment. They are not needed by the Pages app and are not passed to the private workload executed on GitHub's public runner.

## 6. Acceptance test

Once the Worker has all three GitHub App values:

1. Confirm the Worker `/health` endpoint returns an object containing:
   - `ok: true`
   - `mode: cron-only`
   - `runtime_attestation: required`
2. Trigger the public `Encrypted Private Compute` workflow with:
   - contract: `python-bundle-v1`
   - workload: `producer-selftest-v1`
3. Do not manually post an envelope.
4. Within roughly two minutes the Worker cron should discover the one-run recipient.
5. The Worker must verify that the GitHub run references the trusted reusable workflow SHA before reading any private workload.
6. The public runtime should consume the ciphertext, execute the fixed private contract, and publish encrypted result ciphertext only.
7. A later Worker cron should decrypt the result and store it under the private repository's `producer/results/producer-selftest-v1/` path.
8. The private result should contain `round_trip: ok` and `value: 73`.

That full unattended round trip is the release gate for enabling real private workloads such as authenticated MAC.BID account-state processing.

## Trusted runtime pins

The private registry currently pins:

- reusable runtime workflow SHA: `646afc3a233f8a9739b252925d94592b30fea470`
- public runtime source SHA: `c09bac2079895d3f41cb346d2a9adf67369f0fb9`

Changing private-compute runtime code is therefore an explicit promotion operation: create and test a new runtime, update the private trusted-runtime registry, then repoint the caller. Normal application/UI commits cannot silently change the code that receives private plaintext.
