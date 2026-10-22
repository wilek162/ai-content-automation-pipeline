"""Reproduce failure -> revision -> approval without credentials or network."""

from pathlib import Path
import json
import tempfile
import shutil
from automation_pipeline import runner, state

root = Path("runs").resolve()
with tempfile.TemporaryDirectory() as temp:
    config_path = Path(temp) / "example/config.json"
    shutil.copytree(runner.ASSETS / "example", config_path.parent)
    config = state.read(config_path)
    config.update(output_dir=str(root), fixture_scenario="red")
    state.write(config_path, config)
    path = runner.start(config_path, isolated=True)
manifest, revision = runner.verify(path)
assert revision["quality"]["status"] == "RED"
try:
    runner.approve(root, path.name, manifest["digest"])
except ValueError:
    pass
else:
    raise AssertionError("RED must block approval")
runner.revise(root, path.name, "Resolve the placeholder and clarify review expectations")
manifest, revision = runner.verify(path)
assert revision["quality"]["status"] == "GREEN"
runner.approve(root, path.name, manifest["digest"])
print(json.dumps({"run_id": path.name, "initial": "RED", "revised": "GREEN", "approved": True}))
