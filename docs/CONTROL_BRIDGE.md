# Repo-App Control Bridge

## Purpose

GitHub Pages is an excellent read/presentation surface, but it must remain credential-free. A repo application becomes fully interactive when the Pages UI can request a narrowly allowed action without embedding a GitHub PAT, GitHub App private key, account cookie, or service credential in browser JavaScript.

The reusable pattern is:

```text
GitHub Pages UI
    |
    | POST action id + allowed inputs
    v
Authenticated control bridge
    |
    | validate app/action/input contract
    | obtain short-lived GitHub App installation token
    v
GitHub workflow_dispatch / repository_dispatch
    |
    v
GitHub Actions compute
    |
    v
sanitized run/status result
```

## App-side contract

Each repo app declares its allowed operations in `app/actions.json` using schema `repo-app-actions-v1`.

The public Pages build receives only the sanitized action manifest as `actions.json`. It contains action identifiers, display labels, descriptions, risk classifications, workflow names, allowed input schemas, and safe GitHub fallback URLs. It contains no credential or secret needed to execute an action.

The UI can render the same action surface in two modes:

1. `github_ui_fallback` — open GitHub's authenticated workflow/operator page.
2. `control_bridge` — POST the declared action and allowed inputs to the authenticated broker for one-tap execution.

Changing execution mode must not require redesigning the application UI or workflow contract.

## Recommended broker

A small shared service is preferable to one bespoke backend per repository. A Cloudflare Worker protected by Cloudflare Access is a good fit for the current environment, but any equivalent authenticated serverless endpoint is acceptable.

Recommended responsibilities:

- authenticate the human/operator before accepting commands;
- maintain a server-side allowlist of repo apps and action ids;
- validate request payloads against the declared action contract;
- reject undeclared repositories, workflows, refs, inputs, and arbitrary API paths;
- use a GitHub App installed only on approved repositories;
- mint short-lived installation tokens at execution time instead of storing a personal PAT;
- dispatch only the mapped `workflow_dispatch` or `repository_dispatch` operation;
- issue a correlation/request id;
- expose sanitized execution state to the UI;
- rate-limit commands and suppress duplicate requests;
- keep private repo state and secrets out of public Pages output.

## Request contract

A future generic request can remain compact:

```json
{
  "app_id": "macbid-hunt",
  "action_id": "refresh",
  "request_id": "client-generated-uuid",
  "inputs": {
    "reason": "operator refresh"
  }
}
```

The browser must never supply a repository name, arbitrary workflow filename, GitHub API URL, token, ref, or permission scope that the broker blindly trusts. Those are resolved server-side from the approved action manifest/allowlist.

## Response contract

Suggested accepted response:

```json
{
  "accepted": true,
  "request_id": "client-generated-uuid",
  "app_id": "macbid-hunt",
  "action_id": "refresh",
  "state": "queued",
  "operator_url": "https://github.com/.../actions/..."
}
```

The broker can later expose a corresponding read endpoint for `queued`, `running`, `success`, or `failed` status. The Pages UI should not require privileged GitHub API access to poll a private workflow.

## Risk classes

The action contract should distinguish at least:

- `none` — navigation/read-only links;
- `read_only_compute` — scrape, scan, render, analyze, verify, probe;
- `state_change` — modifies application/repository/private service state;
- `external_side_effect` — sends messages, places orders/bids, changes devices, or affects an external account.

The bridge should require stronger confirmation and policy for higher-risk classes. A generic repo-app framework should never make `external_side_effect` actions one-tap by default simply because the transport can execute them.

For MAC.BID Hunt, current declared actions are intentionally `none` or `read_only_compute`. Bidding/purchasing is not part of the public action contract.

## Public/private boundary

`XoticHaze/Scraper-Public` remains public compute and public presentation.

`XoticHaze/Scraper` is the private authority for any future MAC.BID account/session state. The control bridge may dispatch to either repository using its GitHub App installation, but public Pages must only receive state explicitly approved for public presentation.

If a private workload ever needs public compute, continue using the run-bound encrypted envelope pattern already established in the public-compute architecture rather than publishing private inputs or results into a public repository.

## Why this generalizes

The same UI/control contract can drive different repo apps without changing the transport layer:

```text
MACBid.refresh
MACBid.visual-review
HomeAssistant.probe
HomeAssistant.deploy
MarketResearch.refresh-data
MarketResearch.run-model
ServerHealth.probe
```

Each app owns its action manifest and workflow implementation. The shared control bridge owns authentication, authorization, dispatch, rate limiting, correlation, and sanitized run state.
