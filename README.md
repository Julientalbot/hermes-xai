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

1. `POST /api/plugins/hermes-xai/session`: Hermes uses the profile's xAI sign-in through
   `credentialed_provider_request` to call `POST https://api.x.ai/v1/realtime/client_secrets`
   (300 s TTL). With no sign-in, the backend can use an optional `XAI_API_KEY` through
   `agent.secret_scope.get_secret`. Only the client secret reaches the desktop.
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

Voice uses the profile's xAI Grok (SuperGrok) sign-in on Hermes builds with `xai-oauth`
provider requests. The plugin never holds the OAuth token (catalog rule 11). An optional
`XAI_API_KEY` also supports voice on older builds or profiles without a sign-in;
Collections requires that key. Then click the waveform button in the composer.

Settings (`plugins.entries.hermes-xai.settings`, or the plugin's Settings page):

| key | default | |
|---|---|---|
| `model` | `grok-voice-latest` | or a pinned `grok-voice-*` id |
| `voice` | `eve` | built-in voice or custom voice id |
| `reasoning_effort` | `none` | `none` or `high`; `none` answers fastest, Hermes does the thinking |
| `instructions` | `""` | appended to the voice persona (language, tone) |
| `collections_enabled` | `true` | register `xai_collections_search` |
| `collections_default_ids` | `[]` | collections searched when the model passes none (empty = all) |

## Measured (real key, 2026-10-15)

End-to-end voice call with no microphone: the plugin was installed with `hermes plugins install` into
a throwaway `HERMES_HOME`, served by `hermes serve`, and a spoken question (macOS `say`, 24 kHz mono
PCM16, 3.3 s) was streamed into the realtime socket in 100 ms frames, exactly as the desktop button
does. The delegated request ran as a real Hermes turn (`prompt.submit`, surface `voice-live`, agent
model `grok-4.3`) on the serve's `/api/ws` gateway. Question: *"What time is it right now in Tokyo?
Please check for me."*

| step | run 1 | run 2 |
|---|---|---|
| `POST /api/plugins/hermes-xai/session` (secret minted; key absent from the response) | 925 ms | 394 ms |
| xAI WebSocket open | 855 ms | 924 ms |
| `session.created` → model | `grok-voice-3.0` | `grok-voice-3.0` |
| end of speech → transcript | 0.39 s | 0.55 s |
| end of speech → spoken acknowledgement (first audio) | 1.05 s | 1.03 s |
| end of speech → `hermes_task` call | 1.20 s | 1.34 s |
| Hermes turn (`prompt.submit` → `message.complete`) | 18.1 s* | 6.8 s |
| `[Hermes result]` → first audio of the answer | 1.02 s | 1.31 s |
| end of speech → spoken answer | 20.3 s* | 9.4 s |

Spoken answers: "It's 4:41 PM on October 15 in Tokyo." / "It's 4:42 PM in Tokyo right now." (both
correct). \*Run 1 was the first turn of a fresh profile, which includes Hermes' first-run onboarding.
The voice layer itself answers in about 1 s; the rest is the Hermes turn, which depends on your
model and the task.

Collections, same install, through the registered tool handler: `list_collections` 0.73 s (1
collection, 26 documents); a search returned 3 passages (scores 0.49–0.51) in 1.61 s. The key never
appeared in a tool result.

## Limits

- **Desktop only for voice.** The button lives in the Hermes Desktop composer; the CLI, TUI and
  messaging gateways have no realtime voice from this plugin.
- **API key, not OAuth.** Plugins cannot use a Grok OAuth (SuperGrok) sign-in, so `XAI_API_KEY` is
  required.
- **Results wait for the voice to finish.** A Hermes result that arrives while the voice model is
  speaking is queued and read right after.
- **Collections needs xAI-side storage.** Collections keeps your documents on xAI's servers. If your
  xAI team switches to zero data retention, Collections (and therefore `xai_collections_search`)
  stops working. The voice module was not tested under zero data retention.
- **Read only.** The plugin never creates, uploads or deletes collections or documents (that needs
  xAI's separate management key).
- Not affiliated with xAI or Nous Research.

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
python -m pytest            # 20 tests, no network
HERMES_HOME=$(mktemp -d) hermes plugins validate .
```

MIT licensed.

### Voice with a Hermes xAI sign-in

On Hermes builds supporting `xai-oauth` provider requests, voice prefers the
profile's existing xAI Grok sign-in. Hermes mints a short-lived client secret;
the plugin never receives the OAuth token. `XAI_API_KEY` is optional for voice
and is used only when Hermes reports no sign-in. Request failures do not retry
using a key. Older Hermes builds keep the API-key path. The status endpoint
reports support optimistically; starting a session verifies the sign-in.
Collections still require `XAI_API_KEY`. Set
`plugins.entries.hermes-xai.settings.voice` to `sal` to use Sal.
