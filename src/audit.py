"""Audit event emission.

Every agent invoke and completion POSTs a JSON event to the configured sink so
an external system can see what was dispatched and by whom. Any HTTP endpoint
that accepts a JSON body works; bulletproof-event-router is one such sink.

Failure to emit NEVER blocks the invocation — audit is best-effort, with a
warning logged on failure. Set A2A_AUDIT_EVENT_ROUTER_URL to your own sink.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EVENT_ROUTER_URL = os.environ.get(
    "A2A_AUDIT_EVENT_ROUTER_URL", "http://localhost:8085/events"
)
AUDIT_TIMEOUT_S = float(os.environ.get("A2A_AUDIT_TIMEOUT_S", "1.5"))


async def emit_audit_event(
    *,
    category: str,
    event: str,
    agent_id: str,
    caller_id: str,
    job_id: str,
    trust_level: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """POST a single audit event to event-router. Best-effort, never raises."""
    payload = {
        "category": category,
        "event": event,
        "source": "a2a-gateway",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": caller_id,
        "agent_id": agent_id,
        "job_id": job_id,
        "trust_level": trust_level,
        "extra": extra or {},
    }
    try:
        async with httpx.AsyncClient(timeout=AUDIT_TIMEOUT_S) as client:
            r = await client.post(EVENT_ROUTER_URL, json=payload)
            if r.status_code >= 400:
                logger.warning(
                    "audit emission HTTP %d for %s/%s",
                    r.status_code,
                    category,
                    event,
                )
    except Exception as exc:  # noqa: BLE001 — never break invoke flow on audit failure
        logger.warning("audit emission failed: %s", exc)
