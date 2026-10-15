"""hermes-xai — the xAI API surfaces Hermes core does not cover, as one plugin.

Core already ships xAI as a model provider, ``x_search``, a web-search backend, TTS, STT and Grok
Imagine (image + video). This plugin adds only what is missing:

* **voice** — full-duplex Grok Voice in the Desktop composer. No agent registration: two HTTP routes
  (``dashboard/plugin_api.py``) and ``desktop/plugin.js``; real work is handed to Hermes as a normal
  ``prompt.submit`` on the open chat.
* **collections** — one read-only tool, ``xai_collections_search``, over documents already indexed in
  the user's xAI Collections (``POST /v1/documents/search``).

The key is read per call through ``agent.secret_scope.get_secret`` (catalog rule 11) and only sent to
``api.x.ai``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

try:  # loaded by Hermes as a package rooted at the plugin directory
    from .hermes_xai import collections_search as cs
except ImportError:  # imported bare (pytest collecting the repo root)
    from hermes_xai import collections_search as cs  # type: ignore[no-redef]

logger = logging.getLogger("hermes-xai")

TOOLSET = "xai_collections"

COLLECTIONS_SEARCH_SCHEMA: Dict[str, Any] = {
    "name": "xai_collections_search",
    "description": (
        "Search the user's own documents indexed in xAI Collections (console.x.ai) and return the "
        "best-matching passages with their file title and score. Use it when the user refers to their "
        "uploaded documents, knowledge base or a named collection. Read only. Leave collection_ids empty "
        "to search the configured default collections, or all of them; pass list_collections=true to "
        "see which collections exist."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in natural language."},
            "collection_ids": {
                "type": "array", "items": {"type": "string"},
                "description": "Optional collection ids (collection_<uuid>).",
            },
            "limit": {"type": "integer", "description": "Passages to return (1-20, default 5)."},
            "filter": {
                "type": "string",
                "description": "Optional metadata filter, AIP-160 syntax, e.g. year > 2024 AND type = \"contract\".",
            },
            "list_collections": {
                "type": "boolean",
                "description": "Return the available collections instead of searching.",
            },
        },
        "required": [],
    },
}


def _key() -> str:
    try:
        from agent.secret_scope import UnscopedSecretError, get_secret
    except ImportError:  # outside Hermes (tests, linters)
        return (os.environ.get("XAI_API_KEY") or "").strip()
    try:
        return (get_secret("XAI_API_KEY") or "").strip()
    except UnscopedSecretError:
        return (os.environ.get("XAI_API_KEY") or "").strip()


def _available() -> bool:
    return bool(_key())


def make_handler(get_default_ids=lambda: None, requester=None, key_fn=None):
    key_fn = key_fn or _key

    def handle(args: Dict[str, Any], **_kw: Any) -> str:
        args = args or {}
        try:
            if args.get("list_collections"):
                return json.dumps({"collections": cs.list_collections(key_fn(), requester=requester)},
                                  ensure_ascii=False)
            out = cs.search(key_fn(), args.get("query", ""), args.get("collection_ids"),
                            limit=args.get("limit", cs.DEFAULT_LIMIT), filter=args.get("filter") or "",
                            default_ids=get_default_ids(), requester=requester)
            return json.dumps(out, ensure_ascii=False)
        except cs.CollectionsError as exc:
            return json.dumps({"error": exc.message, "reason": exc.reason})
        except Exception as exc:  # a tool handler never raises
            logger.warning("hermes-xai: collections search failed (%s)", type(exc).__name__)
            return json.dumps({"error": f"xai_collections_search failed: {type(exc).__name__}",
                               "reason": "internal"})
    return handle


def register(ctx) -> None:  # noqa: D401 - entry point required by Hermes
    if not ctx.get_config("collections_enabled", default=True):
        return None
    ctx.register_tool(
        name="xai_collections_search", toolset=TOOLSET, schema=COLLECTIONS_SEARCH_SCHEMA,
        handler=make_handler(lambda: ctx.get_config("collections_default_ids", default=None)),
        check_fn=_available, requires_env=["XAI_API_KEY"],
        description="Search your xAI Collections (read only)", emoji="📚",
    )
    return None
