# Public catalog refresh continuity

Current native schedule :17/:47 is best effort, not a delivery SLA. Recent gaps are hours; see issue #72. Do not count missing scans as complete coverage. Keep the existing public catalog workflow and its source/privacy boundaries.

## Fixed authenticated recovery command

On open issue #72 only, the authenticated repository owner (immutable GitHub user ID 152584286) may create a new comment with exactly `refresh-public-catalog-v1`. The existing public workflow checks the fixed issue, owner association, comment author and actor identity, creation event and first run attempt. No parameters, private inputs, credentials, or shell commands. Other comments are skipped and cannot cancel or reserve an active production scan. The workflow uses the default branch source and publishes the same ordinary public catalog. Existing direct workflow dispatch and native schedule remain available. A valid request is not a receipt: verify its specific run and Pages/browser completion. Do not post repeat requests while a scan is active. Pending jobs may be coalesced by GitHub concurrency.

## Automatic scheduling remains a separate acceptance gate

The CommandCenter inventory lists the existing scraper private-envelope producer Worker as source-only, with no verified deployment/custody. Do not change or deploy that private producer merely for a public refresh. Reuse an independently admitted scheduler/credential with access to this exact public refresh command, without adding a new user ChatGPT task, private Actions compute, or arbitrary shell. Native cron remains a fallback. Require repeated automatic scheduled results and actual hourly coverage before declaring cadence restored; no fabricated backfill. The owner-only issue command is a recovery route, not evidence of an unattended scheduler.
