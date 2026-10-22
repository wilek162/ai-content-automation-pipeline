"""Atomic local state, immutable revisions, and scoped process locks."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import tempfile


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_path(root, run_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", run_id):
        raise ValueError("Invalid run ID")
    root = Path(root).resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("Run path escapes output directory")
    return path


@contextmanager
def lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".operation.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(
            f"Another operation owns {path}; after a crash verify no runner is active before removing it"
        )
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def current(path):
    manifest = read(path / "run.json")
    revision = path / "revisions" / f"{manifest['revision']:04d}.json"
    return manifest, read(revision)


def save_revision(path, manifest, revision):
    number = manifest.get("revision", 0) + 1
    target = path / "revisions" / f"{number:04d}.json"
    if target.exists():
        raise ValueError("Refusing to overwrite an immutable revision")
    write(target, revision)
    manifest.update(revision=number, digest=digest(revision), status="needs_review")
    manifest.pop("approval", None)
    write(path / "run.json", manifest)
    (path / "work.json").unlink(missing_ok=True)
    return manifest
