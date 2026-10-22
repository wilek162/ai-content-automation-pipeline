"""Load supplied source text; never fetch source URLs."""

from pathlib import Path
from urllib.parse import urlsplit
import hashlib
from .schemas import SOURCE_MANIFEST, validate
from .state import read


def load(manifest_path, allowed_hosts):
    path = Path(manifest_path)
    result = []
    seen = set()
    for source in validate(read(path), SOURCE_MANIFEST):
        url = urlsplit(source["origin_url"])
        if url.scheme != "https" or url.username or url.password or url.hostname not in allowed_hosts:
            raise ValueError("Source URL must use HTTPS and an explicitly allowed host")
        if source["id"] in seen:
            raise ValueError("Duplicate source ID")
        seen.add(source["id"])
        text_path = (path.parent / source["text_file"]).resolve()
        if not text_path.is_relative_to(path.parent.resolve()):
            raise ValueError("Source text escapes manifest directory")
        raw = text_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("Source text hash mismatch")
        text = raw.decode("utf-8")
        if len(text.strip()) < 80:
            raise ValueError("Source text is too short")
        result.append({k: v for k, v in source.items() if k != "text_file"} | {"text": text})
    return result
