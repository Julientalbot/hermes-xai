"""Behaviour of the session minting core: no network, a fake poster stands in for xAI."""

from __future__ import annotations

import pytest

from hermes_grok_voice import core

KEY = "xai-" + "k" * 40


def _poster(status=200, body=None, calls=None):
    def post(url, headers, payload, timeout):
        if calls is not None:
            calls.append({"url": url, "headers": headers, "payload": payload})
        return status, body if body is not None else {"value": "xai-client-secret-abc", "expires_at": 1_800_000_000}
    return post


def test_mint_sends_the_key_only_to_xai_and_returns_url_secret_and_session_update():
    calls = []
    out = core.mint_session(KEY, {}, poster=_poster(calls=calls))

    assert calls[0]["url"] == "https://api.x.ai/v1/realtime/client_secrets"
    assert calls[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert calls[0]["payload"] == {"expires_after": {"seconds": 300}}
    assert out["url"] == "wss://api.x.ai/v1/realtime?model=grok-voice-latest"
    assert out["client_secret"] == {"value": "xai-client-secret-abc", "expires_at": 1_800_000_000}
    assert out["protocol_prefix"] == "xai-client-secret."
    session = out["session"]
    assert session["voice"] == "eve"
    assert session["turn_detection"] == {"type": "server_vad"}
    assert session["reasoning"] == {"effort": "none"}
    assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert [t["name"] for t in session["tools"]] == ["hermes_task", "end_call"]
    assert KEY not in repr(out)


def test_settings_override_defaults_and_bad_values_fall_back():
    cfg = core.settings({"model": "grok-voice-3.0", "voice": "ara", "reasoning_effort": "high",
                         "instructions": "Answer in French."})
    out = core.mint_session(KEY, cfg, poster=_poster())
    assert out["url"].endswith("?model=grok-voice-3.0")
    assert out["session"]["voice"] == "ara"
    assert out["session"]["reasoning"] == {"effort": "high"}
    assert out["session"]["instructions"].endswith("Answer in French.")

    bad = core.settings({"model": "gpt-4o; drop", "reasoning_effort": "medium", "voice": ""})
    assert bad["model"] == "grok-voice-latest"
    assert bad["reasoning_effort"] == "none"
    assert bad["voice"] == "eve"


@pytest.mark.parametrize("status,reason", [(401, "rejected"), (403, "rejected"), (500, "rejected")])
def test_vendor_refusals_are_typed_and_never_echo_the_key(status, reason):
    body = {"error": f"bad key {KEY}"}
    with pytest.raises(core.VoiceError) as err:
        core.mint_session(KEY, {}, poster=_poster(status=status, body=body))
    assert err.value.reason == reason
    assert KEY not in str(err.value) and KEY not in repr(err.value.detail())


def test_missing_key_and_network_failure():
    with pytest.raises(core.VoiceError) as err:
        core.mint_session("", {}, poster=_poster())
    assert err.value.reason == "no_key" and err.value.status == 503

    def boom(*_a, **_k):
        raise OSError("dns")
    with pytest.raises(core.VoiceError) as err:
        core.mint_session(KEY, {}, poster=boom)
    assert err.value.reason == "unreachable" and err.value.status == 502


def test_a_response_that_echoes_the_key_is_refused():
    with pytest.raises(core.VoiceError):
        core.mint_session(KEY, {}, poster=_poster(body={"value": KEY, "expires_at": 1}))
