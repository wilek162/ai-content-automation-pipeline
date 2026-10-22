"""Explicit configuration; paths are relative to the configuration file."""

from pathlib import Path
from .schemas import CONFIG, validate
from .state import read


def load(path):
    path = Path(path).resolve()
    config = validate(read(path), CONFIG)
    for field in ("source_manifest", "output_dir"):
        config[field] = str((path.parent / config[field]).resolve())
    output = Path(config["output_dir"])
    if output == Path(output.anchor) or output == path.parent or output in path.parents:
        raise ValueError("Output must be a dedicated directory, not a configuration ancestor or drive root")
    if config["provider"] != "fixture" and not config.get("model"):
        raise ValueError("Live providers require an explicit model")
    return config
