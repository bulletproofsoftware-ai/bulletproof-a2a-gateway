"""Shared fixtures.

Every test runs against a purpose-built registry and the ``echo`` executor, so
the suite needs no agent runtime and never shells out.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TEST_REGISTRY = Path(__file__).parent / "fixtures" / "capabilities.test.yaml"

API_KEY = "test-key-primary"
OTHER_KEY = "test-key-secondary"


@pytest.fixture
def app_env(monkeypatch):
    """Configure the environment, then import the app fresh.

    ``src.agents`` builds AGENT_REGISTRY at import time and ``src.rate_limiter``
    reads RATE_LIMIT_RPM at import time, so the modules are reloaded after the
    environment is set rather than before.
    """

    def _configure(**overrides: str):
        env = {
            "A2A_REGISTRY_PATH": str(TEST_REGISTRY),
            "API_KEYS": f"{API_KEY},{OTHER_KEY}",
            "RATE_LIMIT_RPM": "60",
            "A2A_INVOKER_EXECUTOR": "echo",
            # Point audit at a closed port: emission must fail silently.
            "A2A_AUDIT_EVENT_ROUTER_URL": "http://127.0.0.1:1/events",
            "A2A_AUDIT_TIMEOUT_S": "0.05",
        }
        env.update(overrides)
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        for module in (
            "src.agents",
            "src.rate_limiter",
            "src.audit",
            "src.invoker",
            "src.adapters.mcp_bridge",
            "src.main",
        ):
            if module in sys.modules:
                importlib.reload(sys.modules[module])
            else:
                importlib.import_module(module)

        return importlib.import_module("src.main")

    return _configure


@pytest.fixture
def client(app_env):
    """A TestClient bound to a freshly configured app."""
    from fastapi.testclient import TestClient

    def _make(**overrides: str):
        main = app_env(**overrides)
        return TestClient(main.app)

    return _make


@pytest.fixture
def default_client(client):
    return client()
