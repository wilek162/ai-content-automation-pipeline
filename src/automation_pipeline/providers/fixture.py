"""Deterministic fixture provider, never an automatic live-provider fallback."""

from pathlib import Path
from ..state import read


def call(stage, request, config):
    data = read(Path(__file__).parents[1] / "assets/fixtures/default.json")[stage]
    scenario = config.get("fixture_scenario", "default")
    if stage == "write" and scenario == "red" and not request.get("feedback"):
        data["markdown"] += "\n[FACT_CHECK_NEEDED: demonstration of a blocked draft]\n"
    if stage == "write" and request.get("feedback"):
        data["markdown"] += (
            "\n## Review note\n\nThis revision retains the source references for human review.\n"
        )
    return data
