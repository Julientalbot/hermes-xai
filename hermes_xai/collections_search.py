"""xAI Collections search: query documents you already indexed on console.x.ai, from any Hermes turn.

Hermes core has no counterpart (its xAI surface is the model provider, ``x_search``, the web backend,
TTS/STT and Imagine). Two plain REST calls on ``https://api.x.ai`` with ``XAI_API_KEY``:

* ``GET  /v1/collections``       -> the team's collections (id, name, document count)
* ``POST /v1/documents/search``  -> top chunks for a query in one or more collections

Read only: nothing is uploaded, created or deleted. Vendor contract:
https://docs.x.ai/developers/rest-api-reference/collections/search
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

API_BASE = "https://api.x.ai/v1"
LIST_URL = f"{API_BASE}/collections"
SEARCH_URL = f"{API_BASE}/documents/search"
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_CHUNK_CHARS = 2000
_ID_RE = re.compile(r"^collection_[0-9a-f\-]{36}$")

# (method, url, headers, payload | None, timeout) -> (status, body)
Requester = Callable[[str, str, Dict[str, str], Optional[Dict[str, Any]], float], Tuple[int, Any]]


class CollectionsError(Exception):
    """A typed refusal: ``reason`` is machine-readable (no_key, bad_input, rejected, unreachable)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _request(method: str, url: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]],
             timeout: float) -> Tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https origin
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            body = {}
        return exc.code, body


def _call(key: str, method: str, url: str, payload: Optional[Dict[str, Any]],
          requester: Optional[Requester], timeout: float = 30.0) -> Any:
    if not key:
        raise CollectionsError("no_key", "Set XAI_API_KEY on this Hermes profile to search xAI Collections.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        status, body = (requester or _request)(method, url, headers, payload, timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CollectionsError("unreachable", f"xAI unreachable: {type(exc).__name__}") from None
    if status != 200:
        detail = body.get("error") if isinstance(body, dict) else None
        raise CollectionsError("rejected", f"xAI answered HTTP {status}" + (f": {detail}" if detail else ""))
    return body


def list_collections(key: str, *, requester: Optional[Requester] = None) -> List[Dict[str, Any]]:
    body = _call(key, "GET", LIST_URL, None, requester)
    out = []
    for c in (body or {}).get("collections") or []:
        out.append({
            "id": c.get("collection_id"),
            "name": c.get("collection_name"),
            "description": c.get("collection_description") or "",
            "documents": c.get("documents_count"),
        })
    return out


def _clean_ids(ids: Any) -> List[str]:
    if isinstance(ids, str):
        ids = [p for p in re.split(r"[,\s]+", ids) if p]
    cleaned = [str(i).strip() for i in (ids or []) if str(i).strip()]
    bad = [i for i in cleaned if not _ID_RE.match(i)]
    if bad:
        raise CollectionsError("bad_input", f"Not an xAI collection id: {bad[0]!r} (expected collection_<uuid>)")
    return cleaned


def search(key: str, query: str, collection_ids: Sequence[str] | str | None = None, *, limit: int = DEFAULT_LIMIT,
           filter: str = "", default_ids: Sequence[str] | str | None = None,
           requester: Optional[Requester] = None) -> Dict[str, Any]:
    """Top chunks for ``query``. With no ids, falls back to ``default_ids``, then to every collection."""
    query = (query or "").strip()
    if not query:
        raise CollectionsError("bad_input", "query is empty")
    ids = _clean_ids(collection_ids) or _clean_ids(default_ids)
    if not ids:
        ids = [c["id"] for c in list_collections(key, requester=requester) if c.get("id")]
        if not ids:
            raise CollectionsError("bad_input", "This xAI team has no collection yet (create one on console.x.ai).")
    try:
        limit = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    payload: Dict[str, Any] = {"query": query, "source": {"collection_ids": ids}, "limit": limit}
    if (filter or "").strip():
        payload["filter"] = filter.strip()
    body = _call(key, "POST", SEARCH_URL, payload, requester)
    matches = []
    for m in (body or {}).get("matches") or []:
        fields = m.get("fields") or {}
        text = str(m.get("chunk_content") or "")
        matches.append({
            "title": fields.get("title") or m.get("file_id"),
            "file_id": m.get("file_id"),
            "score": m.get("score"),
            "page": m.get("page_number"),
            "text": text[:MAX_CHUNK_CHARS],
        })
    return {"query": query, "collection_ids": ids, "matches": matches}
