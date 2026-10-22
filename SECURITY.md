# Security boundaries

Report security issues privately through GitHub's private vulnerability reporting when available. Do not paste tokens or private source text into public issues. If reporting is unavailable, open a minimal issue requesting a private reporting channel without exploit details or secrets.

The runner never fetches source URLs. It loads local text with hash validation and explicit source hosts. Raw HTML is disabled in previews; active links are rejected. Source documents, model responses, and feedback are untrusted data, never shell commands or executable modules.

Only trusted source commits in main history may process persisted GitHub runs. The data-only state branch is never checked out for execution. Issue bindings are saved separately from editable issue text. Approval covers an immutable revision digest; edits, revisions, or engine changes require a new review.

Repository writers can modify trusted code and runtime state. This project does not protect against a malicious repository administrator. Local approvals are explicitly local acknowledgments. GitHub delivery rechecks the saved approval comment and the reviewer's current write permission.

WordPress authentication uses HTTPS, certificate verification, same-origin requests, and no redirects. Delivery always requests draft status. Remote edits/status changes and uncertain create outcomes block further automatic mutation. This reduces duplicate risk; it does not claim distributed exactly-once delivery or atomic protection against an editor changing a post between read and update.

Budget reservations are conservative estimates for calls made through this runner, not an account-wide spending guarantee or provider invoice. No automatic refunds or rollover occur. Local exclusive lock files prevent concurrent run mutations; after a crash, remove a lock only after verifying that no runner owns it.

Public branches, run bundles, review issues, and workflow artifacts can expose complete source documents and model output. Use demonstration data only in this public repository. Credential-pattern scans are defense in depth and cannot prove that arbitrary content contains no secrets.

If sensitive data is committed, revoke affected credentials first. Removing a working-tree file does not remove history, issues, caches, or downloaded copies.
