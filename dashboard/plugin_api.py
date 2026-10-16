"""Backend half of hermes-xai (voice module), mounted at ``/api/plugins/hermes-xai/``.

* ``GET  /status``  -> ``{available, reason, model, voice}`` (key presence only, never the key)
* ``POST /session`` -> ``{url, protocol_prefix, client_secret: {value, expires_at}, model, session}``

The xAI key is read per request through ``agent.secret_scope.get_secret`` (profile-scoped, catalog
rule 11) and spent only inside :func:`hermes_xai.voice.mint_session`.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from hermes_xai import voice as core  # noqa: E402

logger = logging.getLogger("hermes-xai")
router = APIRouter()
PLUGIN_ID = "hermes-xai"


def _key() -> str:
    try:
        from agent.secret_scope import UnscopedSecretError, get_secret
    except ImportError:  # outside Hermes (tests, linters)
        return (os.environ.get("XAI_API_KEY") or "").strip()
    try:
        return (get_secret("XAI_API_KEY") or "").strip()
    except UnscopedSecretError:  # several profiles, none bound: the env may hold another profile's key
        return ""


def _settings() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly
        entry = (((load_config_readonly() or {}).get("plugins") or {}).get("entries") or {}).get(PLUGIN_ID) or {}
        return core.settings(entry.get("settings"))
    except Exception:
        logger.warning("hermes-xai: settings unreadable, using defaults")
        return core.settings(None)


@router.get("/status")
def status() -> Dict[str, Any]:
    cfg = _settings()
    ready = bool(_key())
    return {
        "available": ready,
        "reason": None if ready else "no_key",
        "message": None if ready else "Set XAI_API_KEY on this Hermes profile to use Grok Voice.",
        "model": cfg["model"],
        "voice": cfg["voice"],
    }


@router.post("/session")
def session(_body: Dict[str, Any] | None = None):
    try:
        out = core.mint_session(_key(), _settings())
    except core.VoiceError as exc:
        logger.info("hermes-xai: session refused (%s)", exc.reason)
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail()})
    logger.info("hermes-xai: client secret minted (model=%s, expires_at=%s)",
                out["model"], out["client_secret"]["expires_at"])
    return out
