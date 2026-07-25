"""API key authentication and trust-level enforcement."""

from __future__ import annotations

import pytest

from tests.conftest import API_KEY

AUTHENTICATED_GETS = ["/api/v1/agents", "/api/v1/jobs/does-not-exist"]


def _invoke(client, agent_id, key=API_KEY, trust=None, caller="test-caller"):
    headers = {}
    if key is not None:
        headers["X-API-Key"] = key
    if trust is not None:
        headers["X-Trust-Level"] = trust
    return client.post(
        f"/api/v1/agents/{agent_id}/invoke",
        json={"prompt": "hello", "caller_id": caller},
        headers=headers,
    )


class TestApiKey:
    def test_health_is_public(self, default_client):
        r = default_client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_agent_card_is_public(self, default_client):
        assert default_client.get("/.well-known/agent.json").status_code == 200

    @pytest.mark.parametrize("path", AUTHENTICATED_GETS)
    def test_missing_key_is_401(self, default_client, path):
        r = default_client.get(path)
        assert r.status_code == 401

    @pytest.mark.parametrize("path", AUTHENTICATED_GETS)
    def test_wrong_key_is_403(self, default_client, path):
        r = default_client.get(path, headers={"X-API-Key": "not-a-real-key"})
        assert r.status_code == 403

    def test_valid_key_is_accepted(self, default_client):
        r = default_client.get("/api/v1/agents", headers={"X-API-Key": API_KEY})
        assert r.status_code == 200

    def test_second_configured_key_is_accepted(self, default_client):
        from tests.conftest import OTHER_KEY

        r = default_client.get("/api/v1/agents", headers={"X-API-Key": OTHER_KEY})
        assert r.status_code == 200

    def test_no_keys_configured_is_500_not_open(self, client):
        """An unconfigured server must fail closed, never allow through."""
        c = client(API_KEYS="")
        r = c.get("/api/v1/agents", headers={"X-API-Key": "anything"})
        assert r.status_code == 500

    def test_invoke_requires_key(self, default_client):
        assert _invoke(default_client, "test-standard", key=None).status_code == 401


class TestTrustLevel:
    def test_standard_agent_needs_no_trust_header(self, default_client):
        assert _invoke(default_client, "test-standard").status_code == 202

    def test_elevated_agent_rejected_without_header(self, default_client):
        """Regression: this path was previously a no-op stub that let callers through."""
        r = _invoke(default_client, "test-elevated")
        assert r.status_code == 403
        assert "elevated" in r.json()["detail"].lower()

    def test_elevated_agent_rejected_with_standard_header(self, default_client):
        assert _invoke(default_client, "test-elevated", trust="standard").status_code == 403

    def test_elevated_agent_allowed_with_elevated_header(self, default_client):
        assert _invoke(default_client, "test-elevated", trust="elevated").status_code == 202

    def test_unknown_agent_is_404(self, default_client):
        assert _invoke(default_client, "no-such-agent").status_code == 404

    def test_hidden_agent_is_not_invocable(self, default_client):
        assert _invoke(default_client, "test-hidden").status_code == 404
