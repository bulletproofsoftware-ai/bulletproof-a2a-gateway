"""Agent registry loaded from registry/capabilities.yaml (PRD-17 REQ-A2A-002).

YAML is the source of truth — adding/removing an agent means editing the YAML
and bouncing the gateway, NOT editing this file.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    """Capability spec for a conductor agent."""

    agent_id: str
    description: str
    allowed_tools: List[str] = field(default_factory=list)
    max_tokens: int = 16384
    externally_callable: bool = True
    trust_level: str = "standard"  # standard | elevated


def _registry_path() -> Path:
    override = os.environ.get("A2A_REGISTRY_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "registry" / "capabilities.yaml"


def _load_yaml_registry() -> Dict[str, AgentSpec]:
    path = _registry_path()
    if not path.exists():
        raise FileNotFoundError(
            f"capabilities.yaml not found at {path}; gateway cannot start without an agent registry"
        )
    with path.open("r") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or "agents" not in doc:
        raise ValueError(f"capabilities.yaml missing 'agents' list (path={path})")
    registry: Dict[str, AgentSpec] = {}
    for entry in doc["agents"]:
        if not entry.get("externally_callable", True):
            continue
        spec = AgentSpec(
            agent_id=entry["agent_id"],
            description=entry["description"],
            allowed_tools=list(entry.get("allowed_tools", [])),
            max_tokens=int(entry.get("max_tokens", 16384)),
            externally_callable=bool(entry.get("externally_callable", True)),
            trust_level=str(entry.get("trust_level", "standard")),
        )
        registry[spec.agent_id] = spec
    logger.info("Loaded %d agents from %s", len(registry), path)
    return registry


AGENT_REGISTRY: Dict[str, AgentSpec] = _load_yaml_registry()


def get_agent(agent_id: str) -> Optional[AgentSpec]:
    """Look up an agent by ID."""
    return AGENT_REGISTRY.get(agent_id)


def list_agents() -> list[dict]:
    """Return all agents as serializable dicts."""
    return [
        {
            "agent_id": a.agent_id,
            "description": a.description,
            "allowed_tools": a.allowed_tools,
            "max_tokens": a.max_tokens,
            "trust_level": a.trust_level,
            "externally_callable": a.externally_callable,
        }
        for a in AGENT_REGISTRY.values()
    ]
