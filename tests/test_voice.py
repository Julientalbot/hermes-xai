"""Behaviour of the session minting core: no network, a fake poster stands in for xAI."""

from __future__ import annotations

import pytest

from hermes_xai import voice as core

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

@pytest.fixture
def oauth(monkeypatch):
    import sys
    from types import SimpleNamespace

    class NotSignedIn(RuntimeError):
        pass

    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(status=200, json=lambda: {"value": "ephemeral-oauth"})

    api = SimpleNamespace(
        ProviderNotSignedIn=NotSignedIn,
        provider_request_capabilities=lambda: {"providers": ["xai-oauth"]},
        credentialed_provider_request=request,
    )
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_provider_requests", api)
    return api, calls


def test_oauth_mint_prefers_sign_in_and_does_not_use_api_key(oauth):
    api, calls = oauth
    def no_key_request(*args):
        pytest.fail("API key must not be used with a sign-in")
    out = core.mint_session(KEY, {"voice": "sal"}, poster=no_key_request)
    assert out["client_secret"]["value"] == "ephemeral-oauth"
    assert out["session"]["voice"] == "sal"
    assert calls == [(("xai-oauth", "POST", core.CLIENT_SECRETS_URL),
                      {"json": {"expires_after": {"seconds": 300}}, "timeout": 20.0})]
    assert KEY not in repr(calls)


def test_oauth_mint_without_key(oauth):
    assert core.mint_session(None, {})["client_secret"]["value"] == "ephemeral-oauth"


def test_missing_sign_in_allows_existing_key_path(oauth):
    api, _ = oauth
    def missing(*args, **kwargs):
        raise api.ProviderNotSignedIn()
    api.credentialed_provider_request = missing
    assert core.mint_session(KEY, {}, poster=_poster())["client_secret"]["value"] == "xai-client-secret-abc"
    with pytest.raises(core.VoiceError, match="Sign in"):
        core.mint_session(None, {})


@pytest.mark.parametrize("failure", [RuntimeError("may have been sent"), PermissionError("undeclared")])
def test_oauth_errors_do_not_fall_back_or_expose_error_details(oauth, failure):
    api, _ = oauth
    def fail(*args, **kwargs):
        raise failure
    api.credentialed_provider_request = fail
    with pytest.raises(core.VoiceError) as err:
        core.mint_session(KEY, {}, poster=lambda *args: pytest.fail("key fallback"))
    assert str(failure) not in str(err.value)


def test_older_hermes_uses_key_path(oauth):
    api, calls = oauth
    api.provider_request_capabilities = lambda: {"providers": ["openai-codex"]}
    assert core.mint_session(KEY, {}, poster=_poster())["client_secret"]["value"] == "xai-client-secret-abc"
    assert calls == []


def test_oauth_vendor_refusal_never_uses_key(oauth):
    from types import SimpleNamespace
    api, _ = oauth
    api.credentialed_provider_request = lambda *a, **k: SimpleNamespace(status=403, json=lambda: {})
    with pytest.raises(core.VoiceError) as err:
        core.mint_session(KEY, {}, poster=lambda *a: pytest.fail("key fallback"))
    assert err.value.reason == "rejected"
