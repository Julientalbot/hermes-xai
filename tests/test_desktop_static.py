"""Static guards on desktop/plugin.js (no browser): the wire contract the backend and xAI expect."""

from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "desktop" / "plugin.js").read_text(encoding="utf-8")


def test_imports_only_the_sdk_and_react():
    imports = [line for line in JS.splitlines() if line.startswith("import ")]
    assert imports == [
        "import { host, icons } from '@hermes/plugin-sdk'",
        "import { createElement as h, useEffect, useState } from 'react'",
    ]


def test_key_never_handled_in_the_renderer():
    assert "XAI_API_KEY" not in JS and "Authorization" not in JS
    assert "new WebSocket(minted.url, [`${minted.protocol_prefix}${minted.client_secret.value}`])" in JS


def test_delegation_rides_the_voice_live_prompt_surface():
    assert "host.request('prompt.submit', { session_id: sid, text: request, surface: 'voice-live'" in JS
    assert "ctx.onEvent('message.complete'" in JS
    assert "[Hermes result]" in JS
