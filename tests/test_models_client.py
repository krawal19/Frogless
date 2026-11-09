"""Offline checks for the model client: no API calls, no credits spent."""

import json

import pytest

from frogless.models import client
from frogless.models.providers import meta


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    cfg = client.load_config()
    path = tmp_path / "calls.jsonl"
    cfg["call_log"] = str(path)  # absolute, so ROOT / path == path
    monkeypatch.setattr(client, "load_config", lambda: cfg)
    return path


def test_charged_segment_failure_is_logged(log_path, monkeypatch):
    def fail(*args, **kwargs):
        raise meta.ProviderError("bad mask", charged=True)

    monkeypatch.setattr(meta, "segment", fail)
    with pytest.raises(meta.ProviderError):
        client.segment("segment", "https://example.com/x.jpg", "crochet")

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["error"] == "bad mask"
    assert entry["cost_usd"] == 0.0025


def test_uncharged_failure_is_logged_without_cost(log_path, monkeypatch):
    def fail(*args, **kwargs):
        raise meta.ProviderError("network error: ReadTimeout: timed out", retryable=True)

    monkeypatch.setattr(meta, "chat", fail)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    with pytest.raises(meta.ProviderError):
        client.chat("translator", [{"role": "user", "content": "hi"}])

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["role"] == "translator" and entry["model"]
    assert "ReadTimeout" in entry["error"] and entry["cost_usd"] is None
    assert entry["latency_ms"] >= 0


def test_provider_error_is_exported_for_callers_outside_models():
    assert client.ProviderError is meta.ProviderError


def test_unreadable_chat_reply_is_charged(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": []}

    monkeypatch.setenv("META_API_KEY", "test")
    monkeypatch.setattr(meta.httpx, "post", lambda *a, **k: FakeResponse())
    cfg = {"api_key_env": "META_API_KEY", "base_url": "https://example.com"}
    with pytest.raises(meta.ProviderError) as err:
        meta.chat(cfg, "m", [])
    assert err.value.charged


def test_bad_stream_is_wrapped_and_charged():
    events = [{"type": "response.failed", "response": {"error": {"message": "boom"}}}]
    with pytest.raises(meta.ProviderError) as err:
        meta._parse_events(events)
    assert err.value.charged
