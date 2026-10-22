# Demonstration output

The project-authored example explains scheduled copies, restore checks, and visible failures. A complete run exports:

- `draft.md` and a safe `preview.html`.
- `quality_report.json`, including status, word count, warnings, and blockers.
- `evidence_ledger.json`, including exact excerpts, source identity, and review limitations.
- Immutable revision JSON with validated stage outputs, raw responses, requests, fingerprints, and a review digest.

Run `python scripts/demo_walkthrough.py` to produce a RED draft with an unresolved marker, demonstrate blocked approval, create a GREEN revised draft, and record a local acknowledgment. Each run uses a fresh ID and local revision timestamps, so those fields vary; fixture stage content is deterministic.

The **Offline demonstration** Actions workflow attaches the generated walkthrough as a downloadable artifact. The release attaches the verified offline example too. This is a fixture demonstration of engineering behavior, not a claim that a live model wrote the example during each run.
