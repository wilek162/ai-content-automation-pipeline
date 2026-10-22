# Release verification

Verification is recorded against the released source revision. Do not interpret mocked checks as live service verification.

## Required checks

- [x] Fresh virtual environment installation, outside-source CLI help, and built-wheel demo.
- [x] Offline tests with socket denial; Windows/Linux Python 3.11/3.12 CI matrix.
- [x] Static checks, workflow YAML/pinned Actions, source-resource consistency.
- [x] Credential-pattern scan of tracked files and all reachable Git blobs.
- [x] Private publication scan of runtime branch, public examples, artifacts, and history.
- [x] GitHub API setup, generation, revision, stale approval, valid approval, duplicate event, and rejection exercises from the trusted local runner. Actions execution also passed; evidence links are in verification.json.
- [x] Repository visibility and release artifact readback.

## Optional integrations

Paid AI calls are disabled by default. Live Gemini/Anthropic request execution and real WordPress delivery require separate credentials and budget/test-site configuration. SDK request construction and WordPress behavior are covered by offline mocks unless a dated result explicitly says otherwise.

## Rollback

Disable the automation workflow to stop remote mutations. Existing WordPress drafts remain under manual control. Restore a known source tag for local work; do not rewrite immutable run history. A changed engine fingerprint requires a fresh review revision. No command publishes content.

See `verification.json` for recorded local/remote results and run links when a release is prepared.

## Release validation

The repository is public. The Windows/Linux Python 3.11/3.12 matrix passed, including 55 offline tests per environment and built-wheel installation checks. GitHub Actions generation, revision, stale-approval rejection, valid approval and rejection passed. Public source/runtime history and downloaded demo artifacts were inspected. Live paid-provider calls and real WordPress delivery were not performed.
