# grok-voice

Full-duplex **xAI Grok Voice** (`grok-voice-latest`, today `grok-voice-3.0`) in the Hermes Desktop
composer. You talk, Grok answers by voice. When the request needs real work (files, web, memory, an
action), the voice model hands it to Hermes as a normal turn on the open chat and reads out the result.

It is the same pattern as core's GPT-Live mode (`voice.voice_chat_mode: gpt-live`). The difference is
the transport: xAI Realtime is a WebSocket API authenticated by an ephemeral client secret, not WebRTC.

## How it works

1. `POST /api/plugins/grok-voice/session`: the backend reads `XAI_API_KEY` through
   `agent.secret_scope.get_secret`. It calls `POST https://api.x.ai/v1/realtime/client_secrets`
   (300 s TTL) and returns `{url, protocol_prefix, client_secret, model, session}`. The key never
   leaves the backend.
2. The desktop half opens `wss://api.x.ai/v1/realtime?model=…` with the subprotocol
   `xai-client-secret.<value>` and sends the returned `session.update`, which carries the persona,
   server VAD, 24 kHz PCM and the two tools `hermes_task` and `end_call`. It then streams mic audio.
3. `hermes_task` becomes `prompt.submit` on the open chat with `surface: "voice-live"`, the same
   per-turn voice note GPT-Live uses. The session's model, toolset, memory and approvals apply
   unchanged. The turn's `message.complete` text goes back to the voice as a `[Hermes result]`
   message, and the voice summarizes it aloud.

## Install

```bash
hermes plugins install https://github.com/Julientalbot/hermes-grok-voice
```

Needs `XAI_API_KEY` in the profile's `.env`. The installer prompts for it. A Grok OAuth (SuperGrok)
sign-in alone is not used, because plugins never hold OAuth tokens (catalog rule 11). Then click the
waveform button in the composer.

Settings (`plugins.entries.grok-voice.settings`, or the plugin's Settings page):

| key | default | |
|---|---|---|
| `model` | `grok-voice-latest` | or a pinned `grok-voice-*` id |
| `voice` | `eve` | built-in voice or custom voice id |
| `reasoning_effort` | `none` | `none` or `high`; `none` answers fastest, Hermes does the thinking |
| `instructions` | `""` | appended to the voice persona (language, tone) |

## Measured (2026-10-14, real key, `grok-voice-latest`)

| step | run 1 | run 2 |
|---|---|---|
| `POST /session` (client secret minted) | 673 ms | 562 ms |
| WebSocket open | 905 ms | 917 ms |
| `session.created` → model | `grok-voice-3.0` | `grok-voice-3.0` |
| "What is on my calendar tomorrow morning?" → `hermes_task` call | 1.30 s | 1.39 s |
| `[Hermes result]` → first audio | 0.77 s | 1.63 s |

In both runs the voice model delegated the calendar question instead of guessing, and spoke the
injected result back faithfully.

## Disclosure

Pressing the button captures microphone audio and streams it to `api.x.ai` over a WebSocket opened by
the desktop with a 300 s client secret. The backend calls `api.x.ai` once per call to mint that
secret with `XAI_API_KEY`. Delegated requests run as normal Hermes turns in the open chat with the
profile's full toolset. Their final text, up to 3000 characters, plus the last few spoken turns are
sent back to xAI. Nothing is stored by the plugin and no telemetry is emitted. xAI bills voice
sessions per minute on your key.

## Develop

```bash
~/.hermes/hermes-agent/venv/bin/python -m pytest
HERMES_HOME=$(mktemp -d) hermes plugins validate .
```

MIT licensed.
