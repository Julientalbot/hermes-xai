"""grok-voice — xAI Grok Voice for Hermes Desktop.

Nothing is registered on the agent: the backend half is two HTTP routes (``dashboard/plugin_api.py``)
and the desktop half is ``desktop/plugin.js``. A delegated request is an ordinary ``prompt.submit``
on the open chat, so the session's model, tools, memory and approvals all apply.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("grok-voice")


def register(ctx) -> None:  # noqa: D401 - entry point required by Hermes
    return None
