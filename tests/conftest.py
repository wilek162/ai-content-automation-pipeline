import socket
import shutil
import pytest
from automation_pipeline import runner, state


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access forbidden in offline tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def example(tmp_path):
    directory = tmp_path / "example"
    shutil.copytree(runner.ASSETS / "example", directory)
    path = directory / "config.json"
    config = state.read(path)
    config["output_dir"] = str(tmp_path / "runs")
    state.write(path, config)
    return path


@pytest.fixture
def completed(example):
    return runner.start(example)
