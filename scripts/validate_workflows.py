"""Validate workflow structure and pinned third-party actions."""

from pathlib import Path
import re
import yaml

for path in Path(".github/workflows").glob("*.yml"):
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert "on" in data and "jobs" in data, path
    assert "schedule" not in data["on"], path
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[a-f0-9]{40}", step["uses"]), step
            assert "${{ github.event.comment.body }}" not in step.get("run", ""), step
print("Workflow YAML and pinned-action checks passed")
