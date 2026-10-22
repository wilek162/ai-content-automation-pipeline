from unittest.mock import Mock
import pytest
from automation_pipeline import runner, state
from automation_pipeline.integrations.wordpress import deliver, reconcile, SecureSession


@pytest.fixture
def client():
    wp = Mock()
    wp.base = "https://wordpress.example.com"
    wp.create.return_value = {"id": 17}
    wp.update.return_value = {"id": 17}

    def post():
        payload = wp.create.call_args[0][0]
        if wp.update.called:
            payload = wp.update.call_args[0][1]
        return {
            "id": 17,
            "title": {"raw": payload["title"]},
            "content": {"raw": payload["content"]},
            "excerpt": {"raw": payload["excerpt"]},
            "status": "draft",
            "categories": [1],
        }

    wp.get.side_effect = lambda _: post()
    return wp


def approved(path):
    manifest, _ = runner.verify(path)
    runner.approve(path.parent, path.name, manifest["digest"])


def test_approval_required(completed, client):
    with pytest.raises(ValueError, match="approval"):
        deliver(completed.parent, completed.name, client=client)
    client.create.assert_not_called()


def test_delivery_idempotent_and_revision_update(completed, client):
    approved(completed)
    first = deliver(completed.parent, completed.name, client=client)
    assert first["status"] == "delivered"
    deliver(completed.parent, completed.name, client=client)
    assert client.create.call_count == 1
    runner.revise(completed.parent, completed.name, "Clarify")
    approved(completed)
    deliver(completed.parent, completed.name, client=client)
    assert client.update.call_count == 1
    assert client.update.call_args[0][1]["status"] == "draft"


def test_create_timeout_never_retries(completed, client):
    approved(completed)
    client.create.side_effect = TimeoutError("unknown")
    with pytest.raises(TimeoutError):
        deliver(completed.parent, completed.name, client=client)
    with pytest.raises(ValueError, match="delivery_unknown"):
        deliver(completed.parent, completed.name, client=client)
    assert client.create.call_count == 1
    client.create.side_effect = None
    receipt = reconcile(completed.parent, completed.name, 17, client=client)
    assert receipt["status"] == "delivered"


def test_readback_mismatch(completed, client):
    approved(completed)
    client.get.side_effect = None
    client.get.return_value = {
        "title": {"raw": "bad"},
        "content": {"raw": "bad"},
        "excerpt": {"raw": "bad"},
        "status": "draft",
    }
    with pytest.raises(ValueError, match="mismatch"):
        deliver(completed.parent, completed.name, client=client)
    assert state.read(completed / "delivery.json")["status"] == "delivery_unknown"


def test_external_edit_blocks_update(completed, client):
    approved(completed)
    deliver(completed.parent, completed.name, client=client)
    client.get.side_effect = None
    client.get.return_value = {
        "title": {"raw": "edit"},
        "content": {"raw": "edit"},
        "excerpt": {"raw": "edit"},
        "status": "publish",
    }
    with pytest.raises(ValueError, match="edited"):
        deliver(completed.parent, completed.name, client=client)
    client.update.assert_not_called()


@pytest.mark.parametrize(
    "url",
    ["http://wordpress.example.com", "https://evil.example", "https://name:secret@wordpress.example.com"],
)
def test_auth_origin_boundary(url):
    session = SecureSession("https://wordpress.example.com")
    with pytest.raises(ValueError):
        session.get(url)


def test_tls_cannot_be_disabled():
    with pytest.raises(ValueError):
        SecureSession("https://wordpress.example.com").get("https://wordpress.example.com", verify=False)
