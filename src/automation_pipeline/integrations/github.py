"""Bounded data-only GitHub state and permission-checked IssueOps."""

import base64
import json
import os
import re
from pathlib import Path
import requests
from .. import state

MAX_BYTES = 512 * 1024


class Conflict(ValueError):
    pass


class GitHub:
    def __init__(self, repo=None, token=None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise ValueError("Explicit OWNER/REPO required")
        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN required")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def api(self, method, path, **kwargs):
        response = self.session.request(
            method,
            f"https://api.github.com/repos/{self.repo}/{path}",
            timeout=30,
            allow_redirects=False,
            **kwargs,
        )
        if response.status_code in {409, 422}:
            raise Conflict("GitHub state conflict; reload and revalidate before retrying")
        response.raise_for_status()
        return response.json() if response.content else None

    def get(self, path):
        response = self.session.get(
            f"https://api.github.com/repos/{self.repo}/contents/{path}",
            params={"ref": "pipeline-state"},
            timeout=30,
            allow_redirects=False,
        )
        if response.status_code == 404:
            return None, None
        response.raise_for_status()
        data = response.json()
        raw = base64.b64decode(data["content"])
        if len(raw) > MAX_BYTES:
            raise ValueError("State bundle exceeds 512 KiB")
        return json.loads(raw), data["sha"]

    def put(self, path, value, sha):
        raw = state.canonical(value).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("State bundle exceeds 512 KiB")
        payload = {
            "branch": "pipeline-state",
            "message": "Update pipeline runtime state",
            "content": base64.b64encode(raw).decode(),
        }
        if sha:
            payload["sha"] = sha
        return self.api("PUT", "contents/" + path, json=payload)["content"]["sha"]

    def setup(self):
        branches = self.api("GET", "branches")
        if not any(b["name"] == "pipeline-state" for b in branches):
            # An empty tree keeps runtime state separate from the source branch.
            tree = self.api(
                "POST",
                "git/trees",
                json={
                    "tree": [
                        {
                            "path": "README.md",
                            "mode": "100644",
                            "type": "blob",
                            "content": "# Runtime state\nPublic demonstration data only. No executable code.\n",
                        }
                    ]
                },
            )
            commit = self.api(
                "POST",
                "git/commits",
                json={"message": "Initialize data-only pipeline state", "tree": tree["sha"], "parents": []},
            )
            self.api("POST", "git/refs", json={"ref": "refs/heads/pipeline-state", "sha": commit["sha"]})
        labels = {item["name"] for item in self.api("GET", "labels", params={"per_page": 100})}
        for label, color in [("needs-review", "D4C5F9"), ("approved", "0E8A16"), ("rejected", "B60205")]:
            if label not in labels:
                self.api("POST", "labels", json={"name": label, "color": color})


def bundle(path):
    manifest = state.read(path / "run.json")
    manifest.pop("config_path", None)
    data = {"schema_version": 1, "manifest": manifest, "files": {}}
    for source in sorted(path.rglob("*.json")):
        name = source.relative_to(path).as_posix()
        if name == "run.json":
            continue
        data["files"][name] = state.read(source)
    if len(state.canonical(data).encode()) > MAX_BYTES:
        raise ValueError("Run bundle exceeds 512 KiB; reduce source material and request size")
    return data


def hydrate(root, data):
    run_id = data["manifest"]["run_id"]
    path = state.run_path(root, run_id)
    state.write(path / "run.json", data["manifest"])
    for name, value in data["files"].items():
        if not re.fullmatch(
            r"(?:revisions/[0-9]{4}|work|delivery|quality_report|evidence_ledger)\.json", name
        ):
            raise ValueError("Unexpected path in data-only bundle")
        state.write(path / name, value)
    return path


class RemoteRun:
    def __init__(self, github, run_id):
        state.run_path(Path.cwd(), run_id)
        self.github, self.run_id = github, run_id
        self.value, self.sha = github.get(f"runs/{run_id}.json")

    def save(self, path):
        self.value = bundle(path)
        self.sha = self.github.put(f"runs/{self.run_id}.json", self.value, self.sha)


def parse_command(body):
    body = body.strip()
    match = re.fullmatch(r"/approve ([a-f0-9]{64})", body)
    if match:
        return "approve", match[1]
    if body == "/reject":
        return "reject", ""
    match = re.fullmatch(r"/improve ([\s\S]{1,4000})", body)
    if match and match[1].strip():
        return "improve", match[1].strip()
    raise ValueError("Use /approve <64-character digest>, /improve <feedback>, or /reject")


def authorize(github, event):
    if "pull_request" in event["issue"]:
        raise ValueError("Review commands apply only to issues")
    author = event["comment"]["user"]["login"]
    permission = github.api("GET", f"collaborators/{author}/permission")["permission"]
    if permission not in {"write", "maintain", "admin"}:
        raise ValueError("Repository write permission required")
    return author
