"""Session minting for Grok Voice: the only place the xAI key is used.

The desktop never sees ``XAI_API_KEY``. ``mint_session`` exchanges it for a short-lived client
secret (``POST /v1/realtime/client_secrets``) and returns what the renderer needs to open
``wss://api.x.ai/v1/realtime`` itself: the URL, the secret (sent as the
``xai-client-secret.<value>`` WebSocket subprotocol) and the ``session.update`` body.

Vendor contract: https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech and
https://docs.x.ai/developers/model-capabilities/audio/ephemeral-tokens
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

API_BASE = "https://api.x.ai/v1"
CLIENT_SECRETS_URL = f"{API_BASE}/realtime/client_secrets"
REALTIME_URL = "wss://api.x.ai/v1/realtime"
PROTOCOL_PREFIX = "xai-client-secret."
SECRET_TTL_S = 300

DEFAULT_MODEL = "grok-voice-latest"  # alias of grok-voice-3.0 (Oct 2026)
DEFAULT_VOICE = "eve"
REASONING_EFFORTS = ("none", "high")  # the two values the realtime session accepts
# "none" answers fastest; the voice layer only talks, Hermes does the thinking.
DEFAULT_REASONING = "none"
_MODEL_RE = re.compile(r"^grok-voice-[a-z0-9.\-]+$")
_VOICE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")  # built-in names or a custom voice id

PERSONA = """# Role
You are Hermes, a calm, friendly voice assistant. You are the voice of an agent that works on the user's computer: the agent does the work, you hand it the tasks.

# Objective
Understand what the user wants, hand real work to the agent with `hermes_task`, and say the result when it arrives.

# Flow
- Anything that needs facts, current information, files, the web, memory, or an action: call `hermes_task` with a clear, complete request in the user's own words.
- When you call it, say one very short sentence ("on it"), then wait. Never guess a result.
- A message starting with "[Hermes result]" is the agent's answer: say it in one or two plain sentences. If it says the task failed, say so simply.
- A correction ("no, Thursday") on a running task: call `hermes_task` again with the corrected request.
- Greetings, small talk, or repeating what was just said: answer directly, no tool.
- When the user clearly says goodbye, say goodbye in one sentence, then call `end_call`.

# Limits
- Never say something is done before the result arrives.
- Do not name the tools or the agent; say "let me check", "it's sent".
- If the request is unclear, ask one short question.

# Style
Speak in the user's language. One or two short spoken sentences per turn, no lists, no symbols."""

TOOLS = [
    {
        "type": "function",
        "name": "hermes_task",
        "description": (
            "Hand a task to the Hermes agent (act, search, check, write, remember, use a service). "
            "Returns a receipt at once; the result arrives later in a message starting with "
            "\"[Hermes result]\"."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The complete request, as the user would type it, with every useful detail.",
                }
            },
            "required": ["request"],
        },
    },
    {
        "type": "function",
        "name": "end_call",
        "description": "End the conversation, only after a clear goodbye from the user and your own goodbye.",
        "parameters": {"type": "object", "properties": {}},
    },
]

Poster = Callable[[str, Dict[str, str], Dict[str, Any], float], Tuple[int, Any]]


class VoiceError(Exception):
    """A typed refusal: ``reason`` is machine-readable (no_key, rejected, unreachable)."""

    def __init__(self, reason: str, message: str, status: int = 502):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status = status

    def detail(self) -> Dict[str, str]:
        return {"reason": self.reason, "message": self.message}


def settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``plugins.entries.hermes-xai.settings`` with defaults; invalid values fall back silently
    (xAI accepts an unknown voice without error, so a typo must not reach the wire)."""
    raw = raw if isinstance(raw, dict) else {}
    model = str(raw.get("model") or "").strip()
    voice = str(raw.get("voice") or "").strip()
    effort = str(raw.get("reasoning_effort") or "").strip().lower()
    return {
        "model": model if _MODEL_RE.match(model) else DEFAULT_MODEL,
        "voice": voice if _VOICE_RE.match(voice) else DEFAULT_VOICE,
        "reasoning_effort": effort if effort in REASONING_EFFORTS else DEFAULT_REASONING,
        "instructions": str(raw.get("instructions") or "").strip()[:4000],
    }


def session_update(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The ``session`` object of the first ``session.update`` (fields from the xAI docs)."""
    extra = cfg.get("instructions") or ""
    return {
        "voice": cfg["voice"],
        "instructions": f"{PERSONA}\n\n{extra}" if extra else PERSONA,
        "reasoning": {"effort": cfg["reasoning_effort"]},
        "turn_detection": {"type": "server_vad"},
        "tools": TOOLS,
        "audio": {
            "input": {"format": {"type": "audio/pcm", "rate": 24000}},
            "output": {"format": {"type": "audio/pcm", "rate": 24000}},
        },
    }


def _scrub(text: str, key: str) -> str:
    return (text or "").replace(key, "***") if key else (text or "")


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Tuple[int, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", "replace")[:300]}


def mint_session(key: Optional[str], cfg: Optional[Dict[str, Any]], poster: Optional[Poster] = None) -> Dict[str, Any]:
    """Client secret + URL + ``session.update`` body for the renderer. Raises :class:`VoiceError`."""
    key = (key or "").strip()
    if not key:
        raise VoiceError("no_key", "Grok Voice needs XAI_API_KEY on this Hermes profile.", 503)
    cfg = settings(cfg)  # idempotent: already-clean settings pass through unchanged
    post = poster or _post_json
    try:
        status, body = post(
            CLIENT_SECRETS_URL,
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            {"expires_after": {"seconds": SECRET_TTL_S}},
            20.0,
        )
    except Exception as exc:  # DNS, TLS, timeout
        raise VoiceError("unreachable", f"xAI is unreachable ({type(exc).__name__}).", 502) from None
    if status >= 400 or not isinstance(body, dict):
        raise VoiceError("rejected", _scrub(f"xAI refused the client secret request ({status}).", key), 502)
    nested = body.get("client_secret")
    nested = nested if isinstance(nested, dict) else {}
    value = body.get("value") or nested.get("value")
    expires = body.get("expires_at") or nested.get("expires_at")
    if not isinstance(value, str) or not value or value == key:
        raise VoiceError("rejected", "Unexpected answer from xAI.", 502)
    return {
        "url": f"{REALTIME_URL}?model={cfg['model']}",
        "protocol_prefix": PROTOCOL_PREFIX,
        "client_secret": {"value": value, "expires_at": int(expires) if isinstance(expires, (int, float)) else None},
        "model": cfg["model"],
        "session": session_update(cfg),
    }
