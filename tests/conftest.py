import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def no_profile_oauth(monkeypatch):
    # Unit tests must never inspect the developer's real sign-in or use the network.
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_provider_requests", SimpleNamespace(
        provider_request_capabilities=lambda: {"providers": []},
    ))
