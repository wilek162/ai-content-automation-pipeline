"""Trusted Actions entrypoint. Runtime bundles are data, never executable code."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from .. import runner, state
from ..budget import GitHubBudget
from ..config import load
from .github import GitHub, RemoteRun, authorize, hydrate, parse_command

ROOT = Path(".runtime/runs")


def event():
    return state.read(os.environ["GITHUB_EVENT_PATH"])


def trusted_sha(sha):
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Run does not contain a trusted source commit")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "origin/main"], check=True, capture_output=True
    )
    return sha


def resolve(github, payload):
    operation = payload.get("inputs", {}).get("operation", "generate")
    if os.environ.get("GITHUB_EVENT_NAME") == "issue_comment":
        authorize(github, payload)
        parse_command(payload["comment"]["body"])
        binding, _ = github.get(f"issues/{payload['issue']['number']}.json")
        if not binding:
            raise ValueError("Issue has no persisted review binding")
        remote = RemoteRun(github, binding["run_id"])
        if not remote.value or remote.value["manifest"].get("issue_number") != payload["issue"]["number"]:
            raise ValueError("Issue binding does not match the saved run")
        sha = trusted_sha(remote.value["manifest"]["source_commit"])
    elif operation in {"resume", "deliver", "reconcile"}:
        remote = RemoteRun(github, payload["inputs"]["run_id"])
        if not remote.value:
            raise ValueError("Run not found")
        sha = trusted_sha(remote.value["manifest"]["source_commit"])
    else:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write(f"source_sha={sha}\n")


def summary(path):
    manifest, revision = state.current(path)
    return (
        f"## Review: {revision['outputs']['format']['title']}\n\n"
        f"Run: `{manifest['run_id']}` | revision {manifest['revision']}\n\n"
        f"Technical checks: **{revision['quality']['status']}**. Human factual review required.\n\n"
        f"{revision['outputs']['write']['markdown']}\n\n"
        f"Evidence limits: {revision['evidence']['limitations']}\n\n"
        f"Warnings: {', '.join(revision['quality']['warnings']) or 'none'}\n\n"
        f"Approve this version: `/approve {manifest['digest']}`\n\n"
        "Or use `/improve <feedback>` or `/reject`. Approval never publishes content."
    )


def ensure_issue(github, remote, path):
    manifest = state.read(path / "run.json")
    if manifest.get("issue_number"):
        number = manifest["issue_number"]
        binding, sha = github.get(f"issues/{number}.json")
        if binding and binding["run_id"] != path.name:
            raise ValueError("Issue already bound to a different run")
        if not binding:
            github.put(f"issues/{number}.json", {"run_id": path.name}, sha)
        return
    if manifest.get("issue_create_unknown"):
        raise ValueError("Issue creation outcome unknown; inspect issues and use bind-issue dispatch")
    manifest["issue_create_unknown"] = True
    state.write(path / "run.json", manifest)
    remote.save(path)
    issue = github.api(
        "POST",
        "issues",
        json={
            "title": "Review: " + manifest["config"]["topic"],
            "body": summary(path),
            "labels": ["needs-review"],
        },
    )
    manifest.update(issue_number=issue["number"], issue_create_unknown=False)
    state.write(path / "run.json", manifest)
    remote.save(path)
    _, sha = github.get(f"issues/{issue['number']}.json")
    github.put(f"issues/{issue['number']}.json", {"run_id": manifest["run_id"]}, sha)


def generate(github, inputs):
    config_path = Path(inputs.get("config", "examples/technical-guide/config.json")).resolve()
    if not config_path.is_relative_to(Path("examples").resolve()):
        raise ValueError("Actions configuration must be a trusted file under examples/")
    config = load(config_path)
    key = state.digest(runner.topic_key(config))
    topic_path = f"topics/{key}.json"
    topic, topic_sha = github.get(topic_path)
    # Demonstration runs deliberately get unique identity; normal generation deduplicates remotely.
    isolated = inputs.get("isolated", "false") == "true"
    if topic and not isolated:
        raise ValueError(f"Duplicate topic/locale; resume {topic['run_id']}")
    remote = None

    def persist(path):
        nonlocal remote
        if remote is None:
            remote = RemoteRun(github, path.name)
            if not isolated:
                github.put(topic_path, {"run_id": path.name}, topic_sha)
        remote.save(path)

    path = runner.start(
        config_path, isolated=True, root_override=ROOT, persist=persist, budget=GitHubBudget(github)
    )
    ensure_issue(github, remote, path)
    return path


def process_comment(github, payload):
    author = authorize(github, payload)
    command, argument = parse_command(payload["comment"]["body"])
    issue = payload["issue"]["number"]
    binding, _ = github.get(f"issues/{issue}.json")
    remote = RemoteRun(github, binding["run_id"])
    if remote.value["manifest"].get("issue_number") != issue:
        raise ValueError("Issue binding mismatch")
    path = hydrate(ROOT, remote.value)
    manifest = state.read(path / "run.json")
    identity = str(payload["comment"]["id"])
    operations = manifest.setdefault("handled_comments", {})
    if identity in operations:
        print("Comment already handled or retained for recovery")
        return path
    if manifest["status"] == "rejected":
        raise ValueError("Run is rejected")
    operations[identity] = "started"
    state.write(path / "run.json", manifest)
    remote.save(path)
    if command == "approve":
        runner.approve(
            ROOT,
            path.name,
            argument,
            identity={"kind": "github_review", "author": author, "comment_id": payload["comment"]["id"]},
        )
    elif command == "improve":
        runner.revise(ROOT, path.name, argument, persist=remote.save, budget=GitHubBudget(github))
    else:
        manifest.update(status="rejected")
        manifest.pop("approval", None)
        state.write(path / "run.json", manifest)
    manifest = state.read(path / "run.json")
    manifest["handled_comments"][identity] = "complete"
    state.write(path / "run.json", manifest)
    remote.save(path)
    label = "approved" if command == "approve" else "rejected" if command == "reject" else "needs-review"
    github.api(
        "PATCH",
        f"issues/{issue}",
        json={"state": "closed" if command == "reject" else "open", "labels": [label], "body": summary(path)},
    )
    github.api(
        "POST",
        f"issues/{issue}/comments",
        json={
            "body": f"{command} completed for `{path.name}`. "
            + ("No publication was performed." if command != "improve" else summary(path))
        },
    )
    runner.export(path)
    return path


def dispatch(github, payload):
    inputs = payload.get("inputs", {})
    operation = inputs.get("operation", "generate")
    if operation == "setup":
        github.setup()
        return None
    if operation == "budget-init":
        GitHubBudget(github).initialize(inputs["month"], inputs["baseline_usd"])
        return None
    if operation == "generate":
        return generate(github, inputs)
    remote = RemoteRun(github, inputs["run_id"])
    if remote.value is None:
        raise ValueError("Run not found")
    path = hydrate(ROOT, remote.value)
    if operation == "resume":
        runner.resume(
            ROOT,
            path.name,
            persist=remote.save,
            budget=GitHubBudget(github),
            acknowledge_retry=inputs.get("acknowledge_paid_retry") == "true",
        )
        ensure_issue(github, remote, path)
    elif operation == "bind-issue":
        number = int(inputs["issue_number"])
        issue = github.api("GET", f"issues/{number}")
        if path.name not in issue["body"]:
            raise ValueError("Issue does not identify this run")
        old, sha = github.get(f"issues/{number}.json")
        if old and old["run_id"] != path.name:
            raise ValueError("Issue already bound to another run")
        manifest = state.read(path / "run.json")
        manifest.update(issue_number=number, issue_create_unknown=False)
        state.write(path / "run.json", manifest)
        remote.save(path)
        github.put(f"issues/{number}.json", {"run_id": path.name}, sha)
    elif operation == "deliver":
        from .wordpress import deliver

        manifest = state.read(path / "run.json")
        approval = manifest.get("approval", {})
        if approval.get("kind") != "github_review":
            raise ValueError("GitHub delivery requires a GitHub-reviewed approval")
        comment = github.api("GET", f"issues/comments/{approval['comment_id']}")
        if comment["user"]["login"] != approval["author"] or parse_command(comment["body"]) != (
            "approve",
            manifest["digest"],
        ):
            raise ValueError("Saved approval comment was changed or removed")
        authorize(github, {"issue": {}, "comment": comment})
        deliver(ROOT, path.name, persist=remote.save)
    elif operation == "reconcile":
        from .wordpress import reconcile

        reconcile(ROOT, path.name, int(inputs["post_id"]), persist=remote.save)
    else:
        raise ValueError("Unknown operation")
    remote.save(path)
    runner.export(path)
    return path


def main():
    github = GitHub()
    payload = event()
    if len(sys.argv) > 1 and sys.argv[1] == "resolve":
        resolve(github, payload)
        return
    path = (
        process_comment(github, payload)
        if os.environ.get("GITHUB_EVENT_NAME") == "issue_comment"
        else dispatch(github, payload)
    )
    if path:
        print(json.dumps({"run_id": path.name}))
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write(summary(path))


if __name__ == "__main__":
    main()
