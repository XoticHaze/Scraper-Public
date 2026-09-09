# Repo-app privacy boundary

`XoticHaze/Scraper-Public` is a public execution and presentation repository. Its source tree, GitHub Actions workflow definitions, public Pages assets, public catalog snapshots, public hunt profiles, public research annotations, and ciphertext rendezvous objects must all be treated as world-readable.

Security must not depend on hiding any code committed here.

## Public by design

- MAC.BID public catalog fields and auction links.
- Deterministic deal/hunt logic.
- GitHub Actions workflow and encrypted-compute transport source.
- GitHub Pages application source and generated public catalog.
- `app/research_findings.json`: annotations about public auction products that are intentionally suitable for public display.
- One-run public X25519 recipient keys.
- Encrypted workload/result ciphertext and sanitized receipts.

## Local-only browser state

The current starred MAC.BID Watchlist is stored in browser `localStorage` under `macbid-hunt-watchlist`.

It is not uploaded by the Pages application, not committed to the repository, and not included in generated Pages artifacts. It therefore remains local to that browser/profile/device unless the operator explicitly exports or synchronizes it in a future feature.

Local browser storage is not a substitute for encrypted account storage: clearing browser data, using another browser/device, or private browsing can make that state unavailable.

## Private authority

`XoticHaze/Scraper` is the authority for material that must not be public, including authenticated MAC.BID account/session state, account-derived watchlists/history, bids/wins, private preference models, private workloads, producer result keys, and decrypted private-compute results.

Those materials may use public GitHub compute only through the run-bound encrypted-compute protocol. Plaintext private source/data/results must never be committed to `Scraper-Public`, emitted to Actions logs, published in Pages, or persisted on the public rendezvous branch.

## Source visibility vs write protection

The source code in `Scraper-Public` is publicly readable because the repository is public. That is intentional. Public readability does not grant write access: repository writes remain controlled by GitHub repository permissions. Branch/ruleset protection is a separate integrity control and should be enabled where useful, but it does not make public source confidential.

Private source in `XoticHaze/Scraper` remains private according to that repository's GitHub access controls and is only transferred to public compute as authenticated ciphertext.

## Trusted producer

The private envelope producer is designed so its implementation may be public while its credentials remain secret in the trusted deployment environment. The deployed Worker requires:

- GitHub App ID;
- GitHub App installation ID;
- GitHub App private key.

The GitHub App must be narrowly installed only on the repositories needed by the producer and granted only the repository permissions required by the protocol. The Worker uses a cron catch-up loop; it does not expose a public endpoint capable of selecting private paths or arbitrary workflows.

## Rule of thumb

If learning the value would reveal something about the operator's account, behavior, private code, credentials, bids, saved items across devices, or private research state, treat it as private authority data. If it is derived solely from public MAC.BID inventory and is safe to show any visitor to the Pages site, it may be public projection data.
