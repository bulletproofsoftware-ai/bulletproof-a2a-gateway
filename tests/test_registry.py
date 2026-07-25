"""Registry loading, and that the shipped YAML files stay valid."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.conftest import API_KEY

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_REGISTRIES = [
    REPO_ROOT / "registry" / "capabilities.yaml",
    REPO_ROOT / "examples" / "capabilities.conductor.yaml",
]


class TestRegistryLoading:
    def test_externally_callable_agents_are_listed(self, default_client):
        r = default_client.get("/api/v1/agents", headers={"X-API-Key": API_KEY})
        ids = {a["agent_id"] for a in r.json()["agents"]}
        assert ids == {"test-standard", "test-elevated"}

    def test_non_callable_agents_are_excluded(self, default_client):
        r = default_client.get("/api/v1/agents", headers={"X-API-Key": API_KEY})
        assert "test-hidden" not in {a["agent_id"] for a in r.json()["agents"]}

    def test_count_matches_listing(self, default_client):
        body = default_client.get(
            "/api/v1/agents", headers={"X-API-Key": API_KEY}
        ).json()
        assert body["count"] == len(body["agents"]) == 2

    def test_trust_level_is_surfaced(self, default_client):
        agents = default_client.get(
            "/api/v1/agents", headers={"X-API-Key": API_KEY}
        ).json()["agents"]
        by_id = {a["agent_id"]: a for a in agents}
        assert by_id["test-elevated"]["trust_level"] == "elevated"
        assert by_id["test-standard"]["trust_level"] == "standard"

    def test_health_reports_agent_count(self, default_client):
        assert default_client.get("/health").json()["agent_count"] == 2

    def test_missing_registry_raises(self, monkeypatch, tmp_path):
        import importlib

        monkeypatch.setenv("A2A_REGISTRY_PATH", str(tmp_path / "nope.yaml"))
        import src.agents as agents

        with pytest.raises(FileNotFoundError):
            importlib.reload(agents)

    def test_registry_without_agents_key_raises(self, monkeypatch, tmp_path):
        import importlib

        bad = tmp_path / "bad.yaml"
        bad.write_text("version: '1.0.0'\n")
        monkeypatch.setenv("A2A_REGISTRY_PATH", str(bad))
        import src.agents as agents

        with pytest.raises(ValueError):
            importlib.reload(agents)


class TestAgentCard:
    def test_card_lists_callable_agents(self, default_client):
        card = default_client.get("/.well-known/agent.json").json()
        assert {a["id"] for a in card["agents"]} == {"test-standard", "test-elevated"}

    def test_card_rate_limit_tracks_config(self, client):
        c = client(RATE_LIMIT_RPM="42")
        card = c.get("/.well-known/agent.json").json()
        assert card["rate_limits"]["requests_per_minute"] == 42


@pytest.mark.parametrize("path", SHIPPED_REGISTRIES, ids=lambda p: p.name)
class TestShippedRegistries:
    """The YAML we ship must stay loadable and schema-valid."""

    def test_parses(self, path):
        assert path.exists(), f"{path} is missing"
        doc = yaml.safe_load(path.read_text())
        assert isinstance(doc, dict)
        assert isinstance(doc.get("agents"), list) and doc["agents"]

    def test_entries_have_required_fields(self, path):
        for entry in yaml.safe_load(path.read_text())["agents"]:
            assert entry.get("agent_id"), f"missing agent_id in {path.name}"
            assert entry.get("description"), f"missing description for {entry}"

    def test_trust_levels_are_known(self, path):
        for entry in yaml.safe_load(path.read_text())["agents"]:
            assert entry.get("trust_level", "standard") in {"standard", "elevated"}

    def test_agent_ids_are_unique(self, path):
        ids = [e["agent_id"] for e in yaml.safe_load(path.read_text())["agents"]]
        assert len(ids) == len(set(ids))

    def test_no_owner_specific_residue(self, path):
        """The default registry must not re-acquire environment-specific paths."""
        text = path.read_text()
        for pattern in ("/Users/", "${HOME}/Code", "host.docker.internal"):
            assert pattern not in text, f"{pattern} found in {path.name}"
