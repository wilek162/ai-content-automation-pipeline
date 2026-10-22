"""Four-stage runner with immutable revisions and interruption checkpoints."""

from pathlib import Path
from uuid import uuid4
import getpass
import importlib.util
import json
import os
import time
import unicodedata
from . import state
from .budget import LocalBudget, estimate
from .config import load
from .evidence import build
from .quality import audit
from .rendering import preview
from .schemas import SCHEMAS, validate
from .sources import load as load_sources

ASSETS = Path(__file__).parent / "assets"
STAGES = ("research", "outline", "write", "format")


def fingerprint():
    root = Path(__file__).parent
    return state.digest(
        {
            p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*"))
            if p.suffix in {".py", ".md", ".json"}
        }
    )


def portable(config):
    return {k: v for k, v in config.items() if k not in {"output_dir", "source_manifest"}}


def topic_key(config):
    return (
        " ".join(unicodedata.normalize("NFKC", config["topic"]).casefold().split()),
        config["locale"].casefold(),
    )


def preflight_live(config):
    if config["provider"] == "fixture":
        return
    module, key = (
        ("google.genai", "GEMINI_API_KEY")
        if config["provider"] == "gemini"
        else ("anthropic", "ANTHROPIC_API_KEY")
    )
    try:
        available = importlib.util.find_spec(module)
    except ModuleNotFoundError:
        available = None
    if available is None:
        raise ValueError(f"Install the '{config['provider']}' optional extra before live execution")
    if not os.environ.get(key, "").strip():
        raise ValueError(f"Set {key} before live execution")
    estimate(config, {})


def start(config_path, *, isolated=False, root_override=None, persist=None, budget=None):
    config = load(config_path)
    root = Path(root_override or config["output_dir"])
    with state.lock(root):
        sources = load_sources(config["source_manifest"], config["allowed_source_hosts"])
        preflight_live(config)
        if not isolated:
            for path in root.glob("*/run.json"):
                existing = state.read(path)
                if topic_key(existing["config"]) == topic_key(config):
                    raise ValueError(f"Duplicate topic/locale; resume existing run {existing['run_id']}")
        run_id = "run-" + uuid4().hex[:20]
        path = state.run_path(root, run_id)
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "revision": 0,
            "status": "running",
            "config": portable(config),
            "config_path": str(Path(config_path).resolve()),
            "source_commit": os.environ.get("PIPELINE_SOURCE_COMMIT", "local"),
            "created_at": state.now(),
        }
        state.write(path / "run.json", manifest)
        work = {
            "config": portable(config),
            "sources": sources,
            "outputs": {},
            "checkpoints": {},
            "engine": fingerprint(),
            "feedback": "",
            "requests": {},
            "responses": {},
        }
        state.write(path / "work.json", work)
        if persist:
            persist(path)
        execute(path, work, persist=persist, budget=budget)
    return path


def execute(path, work, *, acknowledge_retry=False, persist=None, budget=None):
    manifest = state.read(path / "run.json")
    config = work["config"]
    outputs = work["outputs"]

    def checkpoint():
        state.write(path / "work.json", work)
        if persist:
            persist(path)

    work["engine"] = fingerprint()
    for stage in STAGES:
        prompt = (ASSETS / "prompts" / f"{stage}.md").read_text(encoding="utf-8")
        request = {
            "stage": stage,
            "prompt": prompt,
            "schema": SCHEMAS[stage],
            "input": {
                "job": config,
                "sources": work["sources"],
                "previous_stages": {s: outputs[s] for s in STAGES[: STAGES.index(stage)]},
                "feedback": work.get("feedback", ""),
                "previous_draft": work.get("previous_draft", ""),
            },
            "feedback": work.get("feedback", ""),
        }
        expected = state.digest({"request": request, "engine": work["engine"]})
        saved = work["checkpoints"].get(stage, {})
        if saved.get("status") == "complete" and saved.get("input_hash") == expected and stage in outputs:
            if saved.get("output_hash") == state.digest(outputs[stage]):
                continue
        if saved.get("status") in {"request_sent", "outcome_unknown"} and config["provider"] != "fixture":
            saved["status"] = "outcome_unknown"
            checkpoint()
            if not acknowledge_retry:
                raise ValueError(
                    "Paid request outcome unknown; inspect state then use --acknowledge-paid-retry"
                )
        if not (work.get("reuse_prefix") and stage in {"research", "outline"}):
            for downstream in STAGES[STAGES.index(stage) :]:
                outputs.pop(downstream, None)
        if work.get("reuse_prefix") and stage in {"research", "outline"} and stage in outputs:
            work["requests"][stage] = request
            work["responses"][stage] = outputs[stage]
            work["checkpoints"][stage] = {
                "status": "complete",
                "input_hash": expected,
                "output_hash": state.digest(outputs[stage]),
                "reused": True,
            }
            checkpoint()
            continue
        work["requests"][stage] = request
        if saved.get("status") == "response_saved" and saved.get("input_hash") == expected:
            raw = work["responses"][stage]
            value = json.loads(raw) if isinstance(raw, str) else raw
            validate(value, SCHEMAS[stage])
            if stage == "research" and build(value, work["sources"])["blockers"]:
                raise ValueError("Research provenance failed; inspect retained raw response")
            outputs[stage] = value
            work["checkpoints"][stage].update(status="complete", output_hash=state.digest(value))
            checkpoint()
            continue
        preflight_live(config)
        for attempt in range(3):
            reservation = None
            if config["provider"] != "fixture":
                amount, limit = estimate(config, request)
                store = budget or LocalBudget(path.parent / "budget.sqlite")
                reservation = store.reserve(amount, limit)
            work["checkpoints"][stage] = {
                "status": "request_sent",
                "input_hash": expected,
                "reservation": reservation,
                "attempt": attempt + 1,
            }
            checkpoint()
            try:
                if config["provider"] == "fixture":
                    from .providers.fixture import call
                else:
                    from .providers.live import call
                raw = call(stage, request, config)
            except Exception as exc:
                work["checkpoints"][stage]["status"] = "outcome_unknown"
                checkpoint()
                # Retry only explicit rate-limit/server responses; each attempt reserves anew.
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if status in {429, 503} and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise
            work["responses"][stage] = raw
            work["checkpoints"][stage]["status"] = "response_saved"
            checkpoint()
            value = json.loads(raw) if isinstance(raw, str) else raw
            validate(value, SCHEMAS[stage])
            if stage == "research" and build(value, work["sources"])["blockers"]:
                raise ValueError("Research provenance failed; inspect retained raw response")
            outputs[stage] = value
            work["checkpoints"][stage].update(status="complete", output_hash=state.digest(value))
            checkpoint()
            break
    report, ledger = audit(outputs, work["sources"], config)
    revision = {
        "schema_version": 1,
        "config": config,
        "sources": work["sources"],
        "outputs": outputs,
        "quality": report,
        "evidence": ledger,
        "engine": work["engine"],
        "requests": work["requests"],
        "responses": work["responses"],
        "checkpoints": work["checkpoints"],
        "feedback": work.get("feedback", ""),
        "created_at": state.now(),
    }
    state.save_revision(path, manifest, revision)
    export(path)
    if persist:
        persist(path)
    return path


def resume(root, run_id, *, acknowledge_retry=False, persist=None, budget=None):
    with state.lock(root):
        path = state.run_path(root, run_id)
        manifest = state.read(path / "run.json")
        if manifest["status"] == "rejected":
            raise ValueError("Rejected runs cannot resume")
        if (path / "work.json").exists():
            work = state.read(path / "work.json")
        else:
            _, previous = state.current(path)
            original = Path(manifest.get("config_path", ""))
            fresh = load(original) if original.is_file() else None
            same_inputs = fresh is None or (
                portable(fresh) == previous["config"]
                and load_sources(fresh["source_manifest"], fresh["allowed_source_hosts"])
                == previous["sources"]
            )
            if previous["engine"] == fingerprint() and same_inputs:
                verify(path)
                return path
            work = {
                k: previous[k]
                for k in ("config", "sources", "outputs", "requests", "responses", "checkpoints")
            }
            work["feedback"] = previous.get("feedback", "")
        original = Path(manifest.get("config_path", ""))
        if original.is_file():
            fresh = load(original)
            work["config"] = portable(fresh)
            work["sources"] = load_sources(fresh["source_manifest"], fresh["allowed_source_hosts"])
        manifest.pop("approval", None)
        state.write(path / "run.json", manifest)
        return execute(path, work, acknowledge_retry=acknowledge_retry, persist=persist, budget=budget)


def revise(root, run_id, feedback, *, persist=None, budget=None):
    if not feedback.strip():
        raise ValueError("Feedback must not be empty")
    with state.lock(root):
        path = state.run_path(root, run_id)
        manifest, revision = verify(path)
        if manifest["status"] == "rejected":
            raise ValueError("Rejected runs cannot be revised")
        manifest.pop("approval", None)
        manifest["status"] = "running"
        state.write(path / "run.json", manifest)
        work = {
            "config": revision["config"],
            "sources": revision["sources"],
            "outputs": {s: revision["outputs"][s] for s in ("research", "outline")},
            "requests": {},
            "responses": {},
            "checkpoints": {},
            "feedback": feedback,
            "previous_draft": revision["outputs"]["write"]["markdown"],
        }
        # Reusing research/outline requires explicit current-engine fingerprints and revalidation.
        for stage in ("research", "outline"):
            validate(work["outputs"][stage], SCHEMAS[stage])
        # execute supports shared checkpoint construction; preserve research/outline through fixture-independent reuse.
        work["reuse_prefix"] = True
        state.write(path / "work.json", work)
        return execute(path, work, persist=persist, budget=budget)


def verify(path):
    manifest, revision = state.current(path)
    if state.digest(revision) != manifest["digest"]:
        raise ValueError("Immutable revision digest mismatch")
    if revision["engine"] != fingerprint():
        raise ValueError("Engine/prompts changed; resume to create a fresh review revision")
    original = Path(manifest.get("config_path", ""))
    if original.is_file():
        fresh = load(original)
        if (
            portable(fresh) != revision["config"]
            or load_sources(fresh["source_manifest"], fresh["allowed_source_hosts"]) != revision["sources"]
        ):
            raise ValueError("Source/configuration changed; resume before reviewing or approving")
    for stage in STAGES:
        validate(revision["outputs"][stage], SCHEMAS[stage])
    report, _ = audit(revision["outputs"], revision["sources"], revision["config"])
    if report != revision["quality"]:
        raise ValueError("Quality report is stale")
    if manifest["status"] == "rejected" or (path / "work.json").exists():
        raise ValueError("Run is rejected or has an unfinished revision")
    return manifest, revision


def approve(root, run_id, digest, identity=None):
    with state.lock(root):
        path = state.run_path(root, run_id)
        manifest, revision = verify(path)
        if digest != manifest["digest"] or revision["quality"]["status"] == "RED":
            raise ValueError("Approval requires the current digest and non-RED quality")
        manifest["approval"] = {
            "digest": digest,
            "revision": manifest["revision"],
            "at": state.now(),
            **(identity or {"kind": "local_acknowledgment", "author": getpass.getuser()}),
        }
        manifest["status"] = "approved"
        state.write(path / "run.json", manifest)
        return manifest


def export(path):
    manifest, revision = state.current(path)
    for name, value in [
        ("quality_report.json", revision["quality"]),
        ("evidence_ledger.json", revision["evidence"]),
    ]:
        state.write(path / name, value)
    draft = revision["outputs"]["write"]["markdown"]
    (path / "draft.md").write_text(draft, encoding="utf-8")
    (path / "preview.html").write_text(
        preview(revision["outputs"]["format"]["title"], draft, revision["quality"]), encoding="utf-8"
    )
    return manifest
