# hermes-xai

The xAI API surfaces **Hermes core does not cover**, as one plugin. Core already handles xAI as a
model provider (Grok on the Responses API, reasoning, function calling, server-side web search),
`x_search`, the `xai` web-search backend, TTS, STT and Grok Imagine (image generation/editing, video
generation/editing/extension). This plugin does not duplicate any of them. It adds two modules:

| module | what you get | xAI endpoint |
|---|---|---|
| **voice** | full-duplex Grok Voice in the Hermes Desktop composer; real work is handed to Hermes | `POST /v1/realtime/client_secrets` + `wss://api.x.ai/v1/realtime` |
| **collections** | `xai_collections_search`, a read-only tool over documents you indexed in xAI Collections | `GET /v1/collections`, `POST /v1/documents/search` |

## Voice

You talk to `grok-voice-latest` (today `grok-voice-3.0`). When the request needs real work (files,
web, memory, an action), the voice model hands it to Hermes as a normal turn on the open chat and
reads out the result. Same pattern as core's GPT-Live mode (`voice.voice_chat_mode: gpt-live`); the
transport differs: xAI Realtime is a WebSocket API authenticated by an ephemeral client secret.

1. `POST /api/plugins/hermes-xai/session`: the backend reads `XAI_API_KEY` through
   `agent.secret_scope.get_secret`, calls `POST https://api.x.ai/v1/realtime/client_secrets` (300 s
   TTL) and returns `{url, protocol_prefix, client_secret, model, session}`. The key never leaves the
   backend.
2. The desktop half opens `wss://api.x.ai/v1/realtime?model=…` with the subprotocol
   `xai-client-secret.<value>` and sends the returned `session.update` (persona, server VAD, 24 kHz
   PCM, tools `hermes_task` and `end_call`), then streams mic audio.
3. `hermes_task` becomes `prompt.submit` on the open chat with `surface: "voice-live"`. The session's
   model, toolset, memory and approvals apply unchanged. The turn's `message.complete` text goes back
   to the voice as a `[Hermes result]` message.

## Collections search

`xai_collections_search(query, collection_ids?, limit?, filter?, list_collections?)` returns the
best-matching passages (title, score, page, text ≤ 2000 chars) from collections you built on
console.x.ai. With no ids it uses `collections_default_ids`, else every collection of the team.
`filter` takes xAI's AIP-160 metadata syntax. Read only: nothing is uploaded, created or deleted.

## Install

```bash
hermes plugins install https://github.com/Julientalbot/hermes-xai
```

Needs `XAI_API_KEY` in the profile's `.env` (the installer prompts for it). A Grok OAuth (SuperGrok)
sign-in alone is not used, because plugins never hold OAuth tokens (catalog rule 11). Then click the
waveform button in the composer, or ask Hermes about your documents.

Settings (`plugins.entries.hermes-xai.settings`, or the plugin's Settings page):

| key | default | |
|---|---|---|
| `model` | `grok-voice-latest` | or a pinned `grok-voice-*` id |
| `voice` | `eve` | built-in voice or custom voice id |
| `reasoning_effort` | `none` | `none` or `high`; `none` answers fastest, Hermes does the thinking |
| `instructions` | `""` | appended to the voice persona (language, tone) |
| `collections_enabled` | `true` | register `xai_collections_search` |
| `collections_default_ids` | `[]` | collections searched when the model passes none (empty = all) |

## Measured (real key)

Voice, 2026-10-14, `grok-voice-latest`, 2 runs:

| step | run 1 | run 2 |
|---|---|---|
| `POST /session` (client secret minted) | 673 ms | 562 ms |
| WebSocket open | 905 ms | 917 ms |
| `session.created` → model | `grok-voice-3.0` | `grok-voice-3.0` |
| "What is on my calendar tomorrow morning?" → `hermes_task` call | 1.30 s | 1.39 s |
| `[Hermes result]` → first audio | 0.77 s | 1.63 s |

Collections, 2026-10-15, through the registered tool handler: `list_collections` 0.53 s (1 collection,
26 documents); a search returned 2 passages with scores in 1.92 s. The key never appeared in a tool
result.

## Disclosure

- **Voice:** pressing the button captures microphone audio and streams it to `api.x.ai` over a
  WebSocket opened by the desktop with a 300 s client secret. The backend calls `api.x.ai` once per
  call to mint that secret. Delegated requests run as normal Hermes turns with the profile's full
  toolset; their final text (up to 3000 characters) plus the last spoken turns are sent back to xAI.
  xAI bills voice minutes on your key.
- **Collections:** each tool call sends the query (and optional filter) to `api.x.ai` with
  `XAI_API_KEY`; returned passages enter the conversation. xAI bills searches on your key.
- Nothing is stored by the plugin and no telemetry is emitted.

## Develop

```bash
~/.hermes/hermes-agent/venv/bin/python -m pytest
HERMES_HOME=$(mktemp -d) hermes plugins validate .
```

MIT licensed.
