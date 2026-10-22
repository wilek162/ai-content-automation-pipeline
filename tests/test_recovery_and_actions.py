from pathlib import Path
from unittest.mock import Mock

import pytest

from automation_pipeline import runner, state
from automation_pipeline.config import load
from automation_pipeline.integrations import actions
from automation_pipeline.integrations.github import MAX_BYTES, bundle, hydrate
from automation_pipeline.providers import fixture, live


def test_packaged_resources_match_browsing_copies():
    root = Path(__file__).parents[1]
    for path in (root / "prompts").glob("*.md"):
        assert path.read_bytes() == (runner.ASSETS / "prompts" / path.name).read_bytes()
    for path in (root / "examples/technical-guide").iterdir():
        assert path.read_bytes() == (runner.ASSETS / "example" / path.name).read_bytes()


def test_source_change_blocks_approval(completed, example):
    manifest, _ = state.current(completed)
    config = state.read(example)
    config["editorial_brief"] += " changed"
    state.write(example, config)
    with pytest.raises(ValueError, match="configuration changed"):
        runner.approve(completed.parent, completed.name, manifest["digest"])


def test_engine_change_invalidates_approval(completed, monkeypatch):
    manifest, _ = state.current(completed)
    monkeypatch.setattr(runner, "fingerprint", lambda: "different-engine")
    with pytest.raises(ValueError, match="Engine/prompts changed"):
        runner.approve(completed.parent, completed.name, manifest["digest"])


def test_bundle_limit(completed):
    manifest = state.read(completed / "run.json")
    manifest["huge"] = "x" * MAX_BYTES
    state.write(completed / "run.json", manifest)
    with pytest.raises(ValueError, match="512 KiB"):
        bundle(completed)


def paid_config(example):
    config = state.read(example)
    config.update(
        provider="gemini",
        model="test-model",
        budget={
            "enabled": True,
            "monthly_limit_usd": "1",
            "input_usd_per_million": "1",
            "output_usd_per_million": "1",
            "pricing_verified_on": "2026-10-22",
            "model": "test-model",
        },
    )
    state.write(example, config)


def test_unknown_paid_outcome_requires_ack(example, monkeypatch):
    paid_config(example)
    monkeypatch.setattr(runner, "preflight_live", lambda _: None)
    monkeypatch.setattr(live, "call", Mock(side_effect=TimeoutError("outcome unknown")))
    budget = Mock()
    budget.reserve.return_value = "reservation"
    with pytest.raises(TimeoutError):
        runner.start(example, budget=budget)
    path = next(Path(load(example)["output_dir"]).glob("run-*"))
    assert budget.reserve.call_count == 1
    with pytest.raises(ValueError, match="acknowledge-paid-retry"):
        runner.resume(path.parent, path.name, budget=budget)
    assert budget.reserve.call_count == 1
    monkeypatch.setattr(live, "call", fixture.call)
    runner.resume(path.parent, path.name, budget=budget, acknowledge_retry=True)
    assert budget.reserve.call_count == 5  # uncertain first request + four explicit stage attempts


def test_saved_response_resumes_without_new_request(example, monkeypatch):
    original = runner.validate
    calls = []

    def interrupted(value, schema):
        if "claims" in value and not calls:
            calls.append(True)
            raise RuntimeError("interruption after raw response saved")
        return original(value, schema)

    monkeypatch.setattr(runner, "validate", interrupted)
    with pytest.raises(RuntimeError):
        runner.start(example)
    path = next(Path(load(example)["output_dir"]).glob("run-*"))
    monkeypatch.setattr(runner, "validate", original)
    original_call = fixture.call
    stages = []

    def tracked(stage, *args):
        stages.append(stage)
        return original_call(stage, *args)

    monkeypatch.setattr(fixture, "call", tracked)
    runner.resume(path.parent, path.name)
    assert stages == ["outline", "write", "format"]


class Remote:
    def __init__(self, github, run_id):
        self.github = github
        self.run_id = run_id
        self.value = github.data

    def save(self, path):
        self.value = bundle(path)
        self.github.data = self.value


class FakeGitHub:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, name):
        if name.startswith("issues/"):
            return {"run_id": self.data["manifest"]["run_id"]}, "sha"
        return self.data, "sha"

    def api(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/permission"):
            return {"permission": "admin"}
        return {}


def test_issue_body_cannot_redirect_and_comment_replay_is_noop(completed, tmp_path, monkeypatch):
    data = bundle(completed)
    data["manifest"]["issue_number"] = 7
    gh = FakeGitHub(data)
    monkeypatch.setattr(actions, "ROOT", tmp_path / "remote")
    monkeypatch.setattr(actions, "RemoteRun", Remote)
    payload = {
        "issue": {"number": 7, "body": "Run: evil-run"},
        "comment": {
            "id": 11,
            "user": {"login": "reviewer"},
            "body": "/approve " + data["manifest"]["digest"],
        },
    }
    path = actions.process_comment(gh, payload)
    assert state.read(path / "run.json")["approval"]["author"] == "reviewer"
    count = len(gh.calls)
    actions.process_comment(gh, payload)
    assert len(gh.calls) == count + 1  # permission read only; no mutation replay


def test_rejection_cannot_resume(completed):
    manifest = state.read(completed / "run.json")
    manifest["status"] = "rejected"
    state.write(completed / "run.json", manifest)
    with pytest.raises(ValueError, match="Rejected"):
        runner.resume(completed.parent, completed.name)


def test_hydration_cannot_execute_paths(completed, tmp_path):
    data = bundle(completed)
    data["files"]["src/automation_pipeline/cli.py"] = "unsafe"
    with pytest.raises(ValueError, match="Unexpected path"):
        hydrate(tmp_path, data)


def test_unfinished_revision_cannot_be_overwritten(completed):
    state.write(completed / "work.json", {"unknown_request": True})
    with pytest.raises(ValueError, match="unfinished revision"):
        runner.revise(completed.parent, completed.name, "Do not replace uncertain work")
    assert state.read(completed / "work.json") == {"unknown_request": True}


def test_gemini_adapter_constructs_valid_sdk_request(monkeypatch):
    import json
    from google import genai

    client = Mock()
    client.models.generate_content.return_value.text = '{"claims": []}'
    constructor = Mock(return_value=client)
    monkeypatch.setattr(genai, "Client", constructor)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    result = live.call(
        "research",
        {"prompt": "Research", "input": {}, "schema": runner.SCHEMAS["research"]},
        {"provider": "gemini", "model": "test-model", "max_output_tokens": 1024},
    )
    assert json.loads(result) == {"claims": []}
    assert constructor.call_args.kwargs["http_options"].retry_options.attempts == 1
    assert client.models.generate_content.call_args.kwargs["config"].thinking_config.thinking_budget == 0
    client.close.assert_called_once()


def test_anthropic_adapter_disables_sdk_retries(monkeypatch):
    import anthropic

    client = Mock()
    client.messages.create.return_value.content = [Mock(type="text", text='{"claims": []}')]
    manager = Mock()
    manager.__enter__ = Mock(return_value=client)
    manager.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=manager)
    monkeypatch.setattr(anthropic, "Anthropic", constructor)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-placeholder")
    live.call(
        "research",
        {"prompt": "Research", "input": {}, "schema": runner.SCHEMAS["research"]},
        {"provider": "anthropic", "model": "test-model", "max_output_tokens": 1024},
    )
    assert constructor.call_args.kwargs["max_retries"] == 0
