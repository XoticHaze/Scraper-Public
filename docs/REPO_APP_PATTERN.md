# Repository-as-Application Pattern

This repository is an example of a broader pattern: use GitHub as both a durable project workspace and a lightweight application platform.

## Shape

```text
sources / external APIs
        ↓
GitHub Actions compute
        ↓
normalized application state
        ↓
static application build
        ↓
GitHub Pages
        ↓
phone / desktop browser
```

The repository is the **compute/control plane**. GitHub Pages is the **always-open user interface** for the newest successful state.

## Trigger model

Use different triggers for different intent.

### 1. Scheduled refresh

For state that changes independently of code, use `schedule`.

Current MAC.BID cadence:

```yaml
schedule:
  - cron: '17,47 * * * *'
```

This refreshes twice per hour without requiring a user session or device to remain online.

### 2. Manual refresh

Use `workflow_dispatch` for an authenticated "refresh now" control from GitHub:

```yaml
workflow_dispatch:
```

The Pages UI can link to the workflow page rather than embedding a PAT or GitHub credential in public JavaScript.

### 3. Cross-repository refresh

Use `repository_dispatch` as a narrow event interface:

```yaml
repository_dispatch:
  types: [refresh]
```

A private repository, coordinator, or future GitHub App can POST a `refresh` event to this public application when something meaningful changes. Keep `client_payload` small and non-sensitive; private data should not be smuggled through a public dispatch payload.

GitHub's REST repository-dispatch endpoint requires a caller token with `Contents: write` for the target repository. Prefer a narrowly scoped GitHub App installation token or fine-grained PAT stored only in the calling private repository.

Example payload:

```json
{
  "event_type": "refresh",
  "client_payload": {
    "reason": "preferences_changed"
  }
}
```

## Security boundary

Never put a GitHub PAT, MAC.BID credential, session cookie, or other secret into GitHub Pages JavaScript.

Public Pages can:

- browse/search/filter public application state
- deep-link to authenticated GitHub controls
- deep-link to external public items
- persist harmless local UI state in browser storage

Private repositories can:

- hold account/session authority
- create encrypted capsules for public compute
- dispatch a public refresh event
- consume private results

## Recommended repository roles

### Public application repository

Owns:

- deterministic public-data collectors
- scoring/ranking logic
- static UI source
- Pages deployment
- public tests and fixtures
- scheduled/manual/dispatch triggers

### Private state repository

Owns:

- credentials and session material
- account-specific collectors
- saved/watchlist/bid history
- private preferences
- encrypted transport/rendezvous machinery

### Optional coordinator repository

Owns cross-project orchestration only when multiple applications need coordination. It can trigger application repos through narrow dispatch events rather than cloning their implementation logic.

## CI vs application refresh

As the project matures, split workflows:

```text
ci.yml
  push / pull_request
  → unit tests
  → fixture UI build
  → no live scrape

refresh.yml
  schedule / workflow_dispatch / repository_dispatch
  → live public scrape
  → rank / verify
  → build current application state
  → smoke test
  → deploy Pages
```

This prevents ordinary code edits from unnecessarily invoking expensive live-data work.

## Acceptance standard

A repository-hosted application is healthy when:

1. a fresh clone contains enough source to reproduce the application;
2. Actions can regenerate the current state without a developer workstation;
3. the latest successful state is visible through one stable Pages URL;
4. the UI provides a direct path to its control workflow;
5. failures remain visible in Actions without replacing the last known-good Pages deployment;
6. private authority is not leaked into public artifacts;
7. another repository can trigger a refresh through a narrow documented event interface.

This is the default pattern to reuse for future small GitHub-hosted tools and operational interfaces.
