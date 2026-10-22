from pathlib import Path
from unittest.mock import Mock
import pytest
from automation_pipeline import runner, state
from automation_pipeline.cli import main
from automation_pipeline.config import load
from automation_pipeline.sources import load as load_sources
from automation_pipeline.rendering import render, preview
from automation_pipeline.integrations.github import bundle, hydrate, parse_command, authorize
from automation_pipeline.providers import fixture


def test_demo_no_credentials(tmp_path, monkeypatch):
    for name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "WP_APP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--output-dir", str(tmp_path / "out"), "demo"]) == 0
    path = next((tmp_path / "out").glob("run-*"))
    _, revision = runner.verify(path)
    assert revision["quality"]["status"] == "GREEN"
    assert (path / "preview.html").exists()


def test_duplicate_and_repeat_demo(example):
    first = runner.start(example)
    with pytest.raises(ValueError, match="Duplicate"):
        runner.start(example)
    assert runner.start(example, isolated=True) != first


def test_resume_reuses_completed_stages(completed, monkeypatch):
    monkeypatch.setattr(fixture, "call", Mock(side_effect=AssertionError("must not call")))
    assert runner.resume(completed.parent, completed.name) == completed
    assert state.read(completed / "run.json")["revision"] == 1


def test_revision_reuses_research_outline(completed, monkeypatch):
    before, revision = state.current(completed)
    runner.approve(completed.parent, completed.name, before["digest"])
    original = fixture.call
    stages = []

    def tracked(stage, request, config):
        stages.append(stage)
        return original(stage, request, config)

    monkeypatch.setattr(fixture, "call", tracked)
    runner.revise(completed.parent, completed.name, "Clarify the conclusion")
    after, revised = runner.verify(completed)
    assert stages == ["write", "format"]
    assert "approval" not in after
    assert after["revision"] == 2
    assert revised["outputs"]["research"] == revision["outputs"]["research"]
    assert (completed / "revisions/0001.json").exists()


def test_red_cannot_approve(example):
    config = state.read(example)
    config["fixture_scenario"] = "red"
    state.write(example, config)
    path = runner.start(example)
    manifest, revision = runner.verify(path)
    assert revision["quality"]["status"] == "RED"
    with pytest.raises(ValueError, match="non-RED"):
        runner.approve(path.parent, path.name, manifest["digest"])
    runner.revise(path.parent, path.name, "Resolve the marked evidence placeholder")
    assert runner.verify(path)[1]["quality"]["status"] == "GREEN"


def test_stale_digest_and_tampering(completed):
    manifest, revision = state.current(completed)
    with pytest.raises(ValueError, match="current digest"):
        runner.approve(completed.parent, completed.name, "0" * 64)
    revision["outputs"]["write"]["markdown"] += "changed"
    state.write(completed / "revisions/0001.json", revision)
    with pytest.raises(ValueError, match="digest mismatch"):
        runner.verify(completed)


def test_source_change_creates_revision(completed, example):
    config = state.read(example)
    config["editorial_brief"] += " More detail."
    state.write(example, config)
    runner.resume(completed.parent, completed.name)
    assert state.read(completed / "run.json")["revision"] == 2


def test_source_hash_and_unknown_config(example):
    config = load(example)
    manifest = Path(config["source_manifest"])
    data = state.read(manifest)
    data[0]["sha256"] = "0" * 64
    state.write(manifest, data)
    with pytest.raises(ValueError, match="hash mismatch"):
        load_sources(manifest, config["allowed_source_hosts"])
    data = state.read(example)
    data["unknown"] = True
    state.write(example, data)
    with pytest.raises(Exception, match="Additional properties"):
        load(example)


@pytest.mark.parametrize("name", ["../escape", "foo/bar", "foo$()", "C:\\escape", "", ".."])
def test_safe_paths(tmp_path, name):
    with pytest.raises(ValueError):
        state.run_path(tmp_path, name)


def test_rendering_is_inert():
    html = render("<script>alert(1)</script>\n\n[x](javascript:alert(1))")
    assert "<script>" not in html
    assert 'href="javascript:' not in html
    assert "&lt;script&gt;" in html
    assert "<title>&lt;b&gt;</title>" in preview("<b>", "# heading", {"status": "GREEN"})


def test_schema_failure_retained(example, monkeypatch):
    monkeypatch.setattr(fixture, "call", lambda *args: {"wrong": True})
    with pytest.raises(Exception):
        runner.start(example)
    path = next(Path(load(example)["output_dir"]).glob("run-*"))
    work = state.read(path / "work.json")
    assert work["responses"]["research"] == {"wrong": True}
    assert work["checkpoints"]["research"]["status"] == "response_saved"
    assert not work["outputs"]


def test_interruption_resume_no_repeated_stages(example, monkeypatch):
    original = fixture.call

    def interrupt(stage, *args):
        if stage == "write":
            raise RuntimeError("interrupted")
        return original(stage, *args)

    monkeypatch.setattr(fixture, "call", interrupt)
    with pytest.raises(RuntimeError):
        runner.start(example)
    path = next(Path(load(example)["output_dir"]).glob("run-*"))
    stages = []

    def tracked(stage, *args):
        stages.append(stage)
        return original(stage, *args)

    monkeypatch.setattr(fixture, "call", tracked)
    runner.resume(path.parent, path.name)
    assert stages == ["write", "format"]


def test_missing_optional_sdk(example, monkeypatch):
    config = state.read(example)
    config.update(provider="anthropic", model="test-model")
    state.write(example, config)
    monkeypatch.setattr(runner.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ValueError, match="optional extra"):
        runner.start(example)


def test_bundle_is_portable_and_bounded(completed, tmp_path):
    data = bundle(completed)
    assert "config_path" not in data["manifest"]
    path = hydrate(tmp_path / "restored", data)
    assert runner.verify(path)[0]["digest"] == data["manifest"]["digest"]
    data["files"]["../unsafe.json"] = {}
    with pytest.raises(ValueError, match="Unexpected path"):
        hydrate(tmp_path / "bad", data)


@pytest.mark.parametrize(
    "body", ["/approve", "/approve bad", "/reject extra", "/improve ", "/approve " + "a" * 64 + " --live"]
)
def test_exact_command_parsing(body):
    with pytest.raises(ValueError):
        parse_command(body)


def test_command_and_permission_checks():
    assert parse_command("/approve " + "a" * 64) == ("approve", "a" * 64)
    assert parse_command("/improve clarify") == ("improve", "clarify")
    gh = Mock()
    gh.api.return_value = {"permission": "read"}
    event = {"issue": {}, "comment": {"user": {"login": "reader"}}}
    with pytest.raises(ValueError, match="write permission"):
        authorize(gh, event)


def test_local_approval_label(completed):
    manifest, _ = runner.verify(completed)
    result = runner.approve(completed.parent, completed.name, manifest["digest"])
    assert result["approval"]["kind"] == "local_acknowledgment"
