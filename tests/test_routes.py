"""The two HTTP routes, mounted on a bare FastAPI app the way the dashboard mounts them."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
KEY = "xai-" + "r" * 40


@pytest.fixture
def api(monkeypatch):
    spec = importlib.util.spec_from_file_location("grok_voice_plugin_api", ROOT / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/grok-voice")
    return module, TestClient(app)


def test_status_reports_presence_never_the_key(api, monkeypatch):
    module, client = api
    monkeypatch.setattr(module, "_key", lambda: KEY)
    monkeypatch.setattr(module, "_settings", lambda: module.core.settings({}))
    body = client.get("/api/plugins/grok-voice/status").json()
    assert body["available"] is True and body["reason"] is None
    assert body["model"] == "grok-voice-latest" and body["voice"] == "eve"
    assert KEY not in str(body)

    monkeypatch.setattr(module, "_key", lambda: "")
    body = client.get("/api/plugins/grok-voice/status").json()
    assert body["available"] is False and body["reason"] == "no_key"


def test_session_mints_through_core_and_maps_refusals(api, monkeypatch):
    module, client = api
    monkeypatch.setattr(module, "_key", lambda: KEY)
    monkeypatch.setattr(module, "_settings", lambda: module.core.settings({}))
    monkeypatch.setattr(module.core, "_post_json",
                        lambda url, headers, payload, timeout: (200, {"value": "xai-client-secret-x", "expires_at": 9}))
    resp = client.post("/api/plugins/grok-voice/session", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_secret"]["value"] == "xai-client-secret-x"
    assert KEY not in resp.text

    monkeypatch.setattr(module.core, "_post_json", lambda *a, **k: (401, {"error": "nope"}))
    resp = client.post("/api/plugins/grok-voice/session", json={})
    assert resp.status_code == 502 and resp.json()["detail"]["reason"] == "rejected"
