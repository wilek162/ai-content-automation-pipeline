"""Public local command interface."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import sys
from . import runner, state
from .budget import LocalBudget


def main(argv=None):
    parser = argparse.ArgumentParser(description="Resumable AI content automation; offline by default")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    subs = parser.add_subparsers(dest="command", required=True)
    demo = subs.add_parser("demo")
    demo.add_argument("--scenario", choices=["default", "red"], default="default")
    run = subs.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    for name in ("resume", "review", "revise", "approve", "deliver", "reconcile"):
        command = subs.add_parser(name)
        command.add_argument("--run-id", required=True)
        if name == "resume":
            command.add_argument("--acknowledge-paid-retry", action="store_true")
        if name == "revise":
            command.add_argument("--feedback-file", type=Path, required=True)
        if name == "approve":
            command.add_argument("--digest", required=True)
        if name == "deliver":
            command.add_argument("--target", choices=["wordpress"], required=True)
        if name == "reconcile":
            command.add_argument("--post-id", type=int, required=True)
    budget = subs.add_parser("budget-init")
    budget.add_argument("--month", required=True)
    budget.add_argument("--baseline-usd", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.output_dir.resolve()
        if args.command == "demo":
            with tempfile.TemporaryDirectory(prefix="content-demo-") as temporary:
                destination = Path(temporary) / "example"
                shutil.copytree(runner.ASSETS / "example", destination)
                config = state.read(destination / "config.json")
                config.update(output_dir=str(root), fixture_scenario=args.scenario)
                state.write(destination / "config.json", config)
                path = runner.start(destination / "config.json", isolated=True)
                result = state.read(path / "run.json")
        elif args.command == "run":
            path = runner.start(args.config)
            result = state.read(path / "run.json")
        elif args.command == "resume":
            path = runner.resume(root, args.run_id, acknowledge_retry=args.acknowledge_paid_retry)
            result = state.read(path / "run.json")
        elif args.command == "review":
            path = state.run_path(root, args.run_id)
            manifest, revision = runner.verify(path)
            runner.export(path)
            result = {
                "run_id": args.run_id,
                "digest": manifest["digest"],
                "quality": revision["quality"],
                "preview": str(path / "preview.html"),
                "evidence": str(path / "evidence_ledger.json"),
            }
        elif args.command == "revise":
            path = runner.revise(root, args.run_id, args.feedback_file.read_text(encoding="utf-8"))
            result = state.read(path / "run.json")
        elif args.command == "approve":
            result = runner.approve(root, args.run_id, args.digest)
        elif args.command in {"deliver", "reconcile"}:
            from .integrations.wordpress import deliver, reconcile

            result = (
                deliver(root, args.run_id)
                if args.command == "deliver"
                else reconcile(root, args.run_id, args.post_id)
            )
        else:
            LocalBudget(root / "budget.sqlite").initialize(args.month, args.baseline_usd)
            result = {"budget_month": args.month, "initialized": True}
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        # Do not print SDK/HTTP exception bodies that may include private input or credentials.
        detail = (
            str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else "Inspect retained stage state"
        )
        print(f"{type(exc).__name__}: {detail}", file=sys.stderr)
        return 1
