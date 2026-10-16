"""_key() never reads the process env when Hermes says no profile scope is bound."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEY = "xai-" + "e" * 40


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel, submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _secret_scope(get_secret):
    mod = types.ModuleType("agent.secret_scope")

    class UnscopedSecretError(RuntimeError):
        pass

    mod.UnscopedSecretError = UnscopedSecretError
    mod.get_secret = lambda name, default=None: get_secret(UnscopedSecretError, name)
    return mod


@pytest.mark.parametrize("rel,name", [("__init__.py", "hx_tool"), ("dashboard/plugin_api.py", "hx_api")])
def test_unscoped_secret_never_falls_back_to_the_process_env(monkeypatch, rel, name):
    module = _load(rel, name)
    monkeypatch.setenv("XAI_API_KEY", KEY)

    def unscoped(err, _name):
        raise err("no profile bound")

    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.secret_scope", _secret_scope(unscoped))
    assert module._key() == ""

    monkeypatch.setitem(sys.modules, "agent.secret_scope", _secret_scope(lambda err, n: "  " + KEY + " "))
    assert module._key() == KEY
