# Architecture

The package separates CLI/configuration, stage orchestration, provider calls, deterministic validators, local persistence, budget stores, and remote adapters. Python package imports have no credential loading or network side effects.

## Data flow

A source manifest pins local UTF-8 files by SHA-256. Research proposes claims and exact excerpts; outline references claims; write produces Markdown with claim markers and source links; format returns portable metadata. Every provider response passes the same local JSON Schema validation.

Each run contains `run.json`, immutable `revisions/0001.json` files, an optional in-progress `work.json`, and an optional `delivery.json`. Human-readable draft/preview/reports are derived exports. Edit configuration or request a revision; editing an exported draft does not edit the authoritative immutable revision.

Stage checkpoints bind job inputs, previous stage outputs, prompt/schema, and engine fingerprint. A saved response survives validation failure. Successful stages are reused only when hashes match. Revision reuses research/outline and reruns write/format. Source or engine changes use resume to create a fresh revision. Approval is removed before unfinished revisions begin.

A paid request journal is persisted before dispatch. Unknown outcomes require explicit retry acknowledgment. Each retry reserves budget separately, and SDK retries are disabled. Explicit HTTP 429/503 responses use at most three runner attempts; other uncertain failures remain held for operator review.

## GitHub state

Main stores source. The orphan `pipeline-state` branch stores only data: bounded run bundles, topic identities, issue bindings, and budget reservations. Each run bundle is limited to 512 KiB, including revision history and stage requests. Large sources and many revisions can exceed this intentionally small limit; reduce inputs or start a new run instead of removing history silently.

Contents API writes use the current SHA. Conflicts fail or revalidate before retry. Code is pinned to the run's source commit and checked against main history. All mutating workflows share one concurrency group; GitHub can supersede pending jobs, so this is not a durable queue. Inspect canceled jobs and submit a fresh command when needed.

Comment IDs record started/completed operations. A repeated comment never repeats its mutation. A failed improvement is recovered with resume; a failed approval can be retried with a new valid comment. Issue creation also records an intent so a network timeout cannot silently create another issue.

## Delivery state

Approval is separate from delivery. The WordPress adapter writes a durable intent, then creates or updates only a draft. Readback must expose authenticated raw fields and match the submitted payload. An uncertain response blocks further requests until explicit post-ID reconciliation. A remote editor changing content or status prevents automatic overwrite.

## Boundaries

This is a content workflow, not a general agent framework. Claim coverage is explicit but incomplete; a human checks meaning and omissions. There are no browser tools, arbitrary source fetching, PHP plugins, schedules, or live-publication commands.
