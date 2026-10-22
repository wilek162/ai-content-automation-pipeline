# Contributing

Use Python 3.11 or 3.12. Install `requirements-dev.lock` and the editable package, then run the test, lint, workflow-validation, and wheel-smoke commands in the README.

All unit tests deny socket connections. Mock SDKs and HTTP boundaries; never add credentials or paid calls to CI. Keep packaged prompts and examples consistent with their root browsing copies. Include a regression test for changes to state, approval, budget, or remote delivery behavior.

Generated runs, private documents, credentials, and runtime databases do not belong on the source branch. Runtime bundles and artifacts become public with the repository. Never rely on issue bodies as authority for run identity or permit source code from the data branch to execute.

Keep pull requests focused. Describe behavior, failure modes, and the checks actually run. Adding live publication or a new remote mutation requires a separate design review.
