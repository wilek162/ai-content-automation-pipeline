"""Scan tracked files and every reachable Git blob for common credential patterns."""

from pathlib import Path
import re
import subprocess

patterns = [
    re.compile(r"gh[pousr]_" + r"[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_" + r"[A-Za-z0-9_]{30,}"),
    re.compile(r"sk-ant-" + r"[A-Za-z0-9_-]{30,}"),
    re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]
tracked = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
for name in filter(None, tracked):
    path = Path(name)
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            raise SystemExit(f"Potential credential in tracked file: {name}")
objects = subprocess.check_output(["git", "rev-list", "--objects", "--all"], text=True).splitlines()
for item in objects:
    sha = item.split()[0]
    kind = subprocess.check_output(["git", "cat-file", "-t", sha], text=True).strip()
    if kind == "blob":
        text = subprocess.check_output(["git", "cat-file", "blob", sha]).decode(errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            raise SystemExit(f"Potential credential in Git blob: {sha}")
print("Tracked files and all reachable Git blobs passed credential-pattern scan")
