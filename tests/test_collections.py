"""xai_collections_search: wire contract and tool behaviour, no network (a fake requester stands in for xAI)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from hermes_xai import collections_search as cs

ROOT = Path(__file__).resolve().parents[1]
KEY = "xai-" + "c" * 40
CID = "collection_aaf86b27-567c-4c82-92b8-cf838dbf179c"


def _requester(calls, list_body=None, search_body=None, status=200):
    def req(method, url, headers, payload, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "payload": payload})
        if url.endswith("/collections"):
            return status, list_body if list_body is not None else {
                "collections": [{"collection_id": CID, "collection_name": "notes", "documents_count": 3}]}
        return status, search_body if search_body is not None else {"matches": [
            {"file_id": "file_1", "chunk_content": "x" * 5000, "score": 0.4, "page_number": 0,
             "fields": {"title": "a.txt"}, "collection_ids": [CID]}]}
    return req


def _plugin():
    spec = importlib.util.spec_from_file_location("hermes_xai_plugin", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["hermes_xai_plugin"] = module
    spec.loader.exec_module(module)
    return module


def test_search_posts_the_documented_body_with_the_key_only_to_xai():
    calls = []
    out = cs.search(KEY, " revenue ", [CID], limit=3, filter='year > 2024', requester=_requester(calls))
    assert calls[0]["method"] == "POST" and calls[0]["url"] == "https://api.x.ai/v1/documents/search"
    assert calls[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert calls[0]["payload"] == {"query": "revenue", "source": {"collection_ids": [CID]}, "limit": 3,
                                   "filter": "year > 2024"}
    m = out["matches"][0]
    assert m["title"] == "a.txt" and m["score"] == 0.4 and len(m["text"]) == cs.MAX_CHUNK_CHARS


def test_no_ids_uses_defaults_then_every_collection():
    calls = []
    cs.search(KEY, "q", None, default_ids=[CID], requester=_requester(calls))
    assert [c["method"] for c in calls] == ["POST"]
    calls.clear()
    out = cs.search(KEY, "q", None, requester=_requester(calls))
    assert [c["method"] for c in calls] == ["GET", "POST"] and out["collection_ids"] == [CID]


@pytest.mark.parametrize("kwargs,reason", [
    ({"key": "", "query": "q"}, "no_key"),
    ({"key": KEY, "query": "  "}, "bad_input"),
    ({"key": KEY, "query": "q", "collection_ids": ["../etc"]}, "bad_input"),
])
def test_refusals_are_typed_and_never_hit_the_network(kwargs, reason):
    calls = []
    with pytest.raises(cs.CollectionsError) as exc:
        cs.search(kwargs["key"], kwargs["query"], kwargs.get("collection_ids", [CID]), requester=_requester(calls))
    assert exc.value.reason == reason and calls == []


def test_limit_is_clamped_and_http_errors_map_to_rejected():
    calls = []
    cs.search(KEY, "q", [CID], limit=500, requester=_requester(calls))
    assert calls[0]["payload"]["limit"] == cs.MAX_LIMIT
    with pytest.raises(cs.CollectionsError) as exc:
        cs.search(KEY, "q", [CID], requester=_requester([], search_body={"error": "nope"}, status=404))
    assert exc.value.reason == "rejected" and KEY not in exc.value.message


def test_tool_handler_returns_json_and_never_raises():
    plugin = _plugin()
    calls = []
    handle = plugin.make_handler(requester=_requester(calls), key_fn=lambda: KEY)
    body = json.loads(handle({"query": "q", "collection_ids": [CID]}))
    assert body["matches"][0]["file_id"] == "file_1"
    listed = json.loads(handle({"list_collections": True}))
    assert listed["collections"] == [{"id": CID, "name": "notes", "description": "", "documents": 3}]
    err = json.loads(plugin.make_handler(requester=_requester([]), key_fn=lambda: "")({"query": "q"}))
    assert err["reason"] == "no_key"


def test_register_adds_one_read_only_tool_and_honours_the_switch():
    plugin = _plugin()

    class Ctx:
        def __init__(self, cfg):
            self.cfg, self.tools = cfg, []

        def get_config(self, key, default=None):
            return self.cfg.get(key, default)

        def register_tool(self, **kw):
            self.tools.append(kw)

    ctx = Ctx({})
    plugin.register(ctx)
    assert [t["name"] for t in ctx.tools] == ["xai_collections_search"]
    assert ctx.tools[0]["toolset"] == "xai_collections" and ctx.tools[0]["requires_env"] == ["XAI_API_KEY"]
    off = Ctx({"collections_enabled": False})
    plugin.register(off)
    assert off.tools == []
