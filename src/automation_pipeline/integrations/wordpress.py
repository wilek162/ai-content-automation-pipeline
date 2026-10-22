"""Standard REST draft delivery. Never publishes or blindly retries creation."""

import os
from urllib.parse import urlsplit
import requests
from .. import state
from ..rendering import render
from ..runner import verify


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("WordPress requires an HTTPS URL without embedded credentials")
    return parsed.scheme, parsed.hostname, parsed.port or 443


class SecureSession(requests.Session):
    def __init__(self, base):
        super().__init__()
        self.expected_origin = origin(base)

    def request(self, method, url, **kwargs):
        if origin(url) != self.expected_origin or kwargs.get("verify") is False or self.verify is False:
            raise ValueError("Authenticated WordPress requests must retain HTTPS and the configured origin")
        kwargs["allow_redirects"] = False
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise ValueError("Authenticated WordPress redirect rejected")
        return response


class WordPress:
    def __init__(self):
        self.base = os.environ.get("WP_URL", "").rstrip("/")
        parsed = urlsplit(self.base)
        origin(self.base)
        if parsed.query or parsed.fragment:
            raise ValueError("WP_URL cannot contain query or fragment")
        user, password = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
        if not user or not password:
            raise ValueError("Set WP_USER and WP_APP_PASSWORD")
        self.session = SecureSession(self.base)
        self.session.auth = (user, password)

    def request(self, method, suffix, **kwargs):
        response = self.session.request(
            method, self.base + "/wp-json/wp/v2/posts" + suffix, timeout=30, **kwargs
        )
        response.raise_for_status()
        return response.json()

    def get(self, post_id):
        return self.request("GET", f"/{int(post_id)}", params={"context": "edit"})

    def create(self, payload):
        return self.request("POST", "", json=payload)

    def update(self, post_id, payload):
        return self.request("POST", f"/{int(post_id)}", json=payload)


def saved_fields(post):
    def raw(field):
        value = post.get(field, {})
        if "raw" not in value:
            raise ValueError("Authenticated edit-context readback must expose raw fields")
        return value["raw"].replace("\r\n", "\n").strip()

    return {
        "title": raw("title"),
        "content": raw("content"),
        "excerpt": raw("excerpt"),
        "status": post.get("status"),
        "categories": sorted(post.get("categories", [])),
    }


def expected_fields(payload, actual):
    result = {
        k: v.replace("\r\n", "\n").strip() if isinstance(v, str) else v
        for k, v in payload.items()
        if k != "categories"
    }
    result["categories"] = sorted(payload.get("categories", actual["categories"]))
    return result


def deliver(root, run_id, *, client=None, persist=None):
    with state.lock(root):
        path = state.run_path(root, run_id)
        manifest, revision = verify(path)
        approval = manifest.get("approval", {})
        if approval.get("digest") != manifest["digest"] or revision["quality"]["status"] == "RED":
            raise ValueError("Current human approval is required")
        client = client or WordPress()
        receipt_path = path / "delivery.json"
        receipt = state.read(receipt_path) if receipt_path.exists() else None
        if receipt and receipt["origin"] != client.base:
            raise ValueError("Delivery origin differs from the saved receipt")
        if receipt and receipt["status"] != "delivered":
            raise ValueError("delivery_unknown: reconcile the previous intent before another request")
        metadata = revision["outputs"]["format"]
        payload = {
            "title": metadata["title"],
            "excerpt": metadata["excerpt"],
            "content": render(revision["outputs"]["write"]["markdown"]),
            "status": "draft",
        }
        categories = revision["config"].get("wordpress", {}).get("category_ids")
        if categories:
            payload["categories"] = categories
        if receipt:
            actual = saved_fields(client.get(receipt["post_id"]))
            if state.digest(actual) != receipt["saved_hash"] or actual["status"] != "draft":
                raise ValueError("Remote post was edited or is no longer a draft")
            if receipt["digest"] == manifest["digest"]:
                return receipt
        intent = {
            "status": "delivery_unknown",
            "origin": client.base,
            "run_id": run_id,
            "digest": manifest["digest"],
            "revision": manifest["revision"],
            "payload": payload,
            "payload_hash": state.digest(payload),
            "post_id": receipt["post_id"] if receipt else None,
            "created_at": state.now(),
        }
        state.write(receipt_path, intent)
        if persist:
            persist(path)
        # No retry here: a timeout may mean the remote mutation succeeded.
        post = client.update(receipt["post_id"], payload) if receipt else client.create(payload)
        intent["post_id"] = post["id"]
        state.write(receipt_path, intent)
        if persist:
            persist(path)
        actual = saved_fields(client.get(post["id"]))
        if actual != expected_fields(payload, actual):
            raise ValueError("WordPress readback mismatch; delivery remains unknown")
        intent.update(status="delivered", saved_hash=state.digest(actual), verified_at=state.now())
        state.write(receipt_path, intent)
        if persist:
            persist(path)
        return intent


def reconcile(root, run_id, post_id, *, client=None, persist=None):
    with state.lock(root):
        path = state.run_path(root, run_id)
        intent = state.read(path / "delivery.json")
        client = client or WordPress()
        if intent["status"] != "delivery_unknown" or intent["origin"] != client.base:
            raise ValueError("No matching uncertain delivery to reconcile")
        if intent.get("post_id") and intent["post_id"] != post_id:
            raise ValueError("Post ID differs from the recorded mutation")
        actual = saved_fields(client.get(post_id))
        if actual != expected_fields(intent["payload"], actual):
            raise ValueError("Specified post does not match the saved delivery intent")
        intent.update(
            status="delivered", post_id=post_id, saved_hash=state.digest(actual), verified_at=state.now()
        )
        state.write(path / "delivery.json", intent)
        if persist:
            persist(path)
        return intent
