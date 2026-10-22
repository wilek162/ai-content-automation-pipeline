# Optional integration setup and recovery

## Live AI

1. Install `pip install '.[gemini]'` or `pip install '.[anthropic]'`.
2. Copy the example config; use your own source manifest and source documents. Set `provider`, an explicit supported `model`, and a budget profile.
3. Set the matching `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` environment variable. Files are not loaded automatically.
4. Verify current model pricing from its provider, then supply these **string-valued** budget fields:

```json
{
  "enabled": true,
  "monthly_limit_usd": "YOUR_REVIEWED_LIMIT",
  "input_usd_per_million": "CURRENT_INPUT_PRICE",
  "output_usd_per_million": "CURRENT_OUTPUT_PRICE",
  "pricing_verified_on": "YYYY-MM-DD",
  "model": "EXACT_SAME_MODEL_AS_JOB"
}
```

5. Initialize the current UTC month with `python -m automation_pipeline budget-init --month YYYY-MM --baseline-usd 0`. Use a reconciled baseline if this managed ledger already has obligations. Initialization cannot overwrite an existing month.
6. Run the configured job. Gemini uses JSON schema output and disables thinking for compatible models; choose a model supporting those options. Anthropic receives the schema in its request and is also validated locally.

A provider failure never switches to fixtures. After an uncertain request, inspect `work.json` and the provider dashboard. Resume with `--acknowledge-paid-retry` only when another chargeable attempt is intended. A saved malformed response is retained for diagnosis; correct inputs/model configuration and resume with changed inputs rather than blindly repeating it.

SDK references: [Google Gen AI Python SDK](https://github.com/googleapis/python-genai), [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python). No current model availability or prices are bundled as defaults.

## GitHub review

After pushing the source to your own repository, enable Actions and run **Pipeline automation → setup**. It creates the data-only state branch and labels idempotently. Set repository Actions token policy to allow the workflow's requested contents/issue writes if your organization restricts them.

Run **generate** with `examples/technical-guide/config.json`. It creates an issue bound to the saved run. The example uses fixtures and no paid credentials. Normal runs deduplicate topic/locale; `isolated=true` deliberately creates a separate demonstration.

Review the draft and evidence in the issue/artifacts. A user with write, maintain, or admin permission can comment:

```text
/approve <current 64-character digest>
/improve Clarify the restore-check explanation
/reject
```

Approval records review only. To deliver, separately dispatch `operation=deliver` with the run ID. The saved approval comment must remain valid and its author must still have write permission.

Use **resume** for a failed stage and select `acknowledge_paid_retry=true` only after reviewing any unknown paid outcome. If an issue-create request was uncertain, inspect existing issues and use **bind-issue** with the run ID and explicit issue number. Bindings cannot redirect an issue already bound to another run.

For live GitHub generation, commit a reviewed configuration under `examples/`, configure new provider secrets, and dispatch **budget-init** for the current UTC month with an explicit baseline. The GitHub ledger is separate from local SQLite. No schedules run automatically.

The repository-wide concurrency group does not guarantee every pending job executes. A canceled pending command can be resubmitted as a new comment. Handled comment IDs prevent replay of the same event. Runtime bundles and artifacts are public data after publication; never supply private documents.

Platform references: [Contents API](https://docs.github.com/en/rest/repos/contents), [workflow event context](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).

## WordPress drafts

Use a separate test WordPress site with HTTPS and an application-password account permitted to edit its own drafts. Set `WP_URL`, `WP_USER`, and `WP_APP_PASSWORD` in your shell, or as new repository secrets. No plugin or SEO extension is required. Optional `wordpress.category_ids` must identify existing categories.

Approve locally using the printed digest, then run `deliver --run-id <id> --target wordpress`. Suggested tags remain local. Publication is manual in WordPress; the adapter cannot publish.

If creation/update times out, delivery remains unknown. Find the intended draft in WordPress and run:

```sh
python -m automation_pipeline reconcile --run-id <id> --post-id <id>
```

Reconciliation checks the configured origin and full saved payload; it never mutates the selected post. A known post ID cannot be replaced with a different one. In Actions use `operation=reconcile`. If no matching post exists, inspect the request outcome manually; v1 deliberately provides no automatic reset-and-create escape hatch.

A changed/deleted/published remote draft blocks further automatic updates. Reconcile external edits manually rather than overwriting them. Changes between pre-read and update cannot be made atomic through the standard posts API.

[Standard posts REST reference](https://developer.wordpress.org/rest-api/reference/posts/).
