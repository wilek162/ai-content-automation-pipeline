"""Exercise the built wheel from a fresh environment outside the source tree."""

from pathlib import Path
import subprocess
import tempfile
import venv

wheel = next(Path("dist").resolve().glob("*.whl"))
with tempfile.TemporaryDirectory(prefix="pipeline-wheel-") as temp:
    root = Path(temp)
    venv.EnvBuilder(with_pip=True).create(root / "venv")
    python = root / "venv" / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", str(wheel)], check=True)
    subprocess.run([str(python), "-m", "automation_pipeline", "--help"], cwd=root, check=True)
    subprocess.run([str(python), "-m", "automation_pipeline", "demo"], cwd=root, check=True)
