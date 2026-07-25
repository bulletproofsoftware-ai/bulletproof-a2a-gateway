"""MCP bridge adapter.

Exposes every agent in the capabilities registry as an MCP tool so any
MCP-aware client (Claude Code, Claude Desktop, the MCP Inspector) can
invoke them.

The MCP protocol over HTTP wraps JSON-RPC 2.0 messages. We implement the
minimum surface needed for tool discovery + invocation:

    POST /mcp        — JSON-RPC entrypoint
        method=initialize      → server info + capabilities
        method=tools/list      → list of tools (one per agent)
        method=tools/call      → invoke agent (synchronous wrapper around job dispatch)

Authentication piggybacks on the same X-API-Key header used by REST endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..agents import get_agent, list_agents
from ..audit import emit_audit_event
from ..auth import require_api_key
from ..invoker import invoke_agent
from ..rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP Bridge"])


def _jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _tool_for_agent(agent_id: str) -> dict:
    a = get_agent(agent_id)
    if not a:
        return {}
    return {
        "name": agent_id,
        "description": a.description,
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The prompt/task to send to the agent",
                    "minLength": 1,
                    "maxLength": 100000,
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context prepended to the prompt",
                    "maxLength": 100000,
                },
                "caller_id": {
                    "type": "string",
                    "description": "Identifier for the calling system (for audit/rate-limit)",
                    "minLength": 1,
                    "maxLength": 256,
                },
            },
            "required": ["prompt", "caller_id"],
            "additionalProperties": False,
        },
        "annotations": {
            "title": agent_id,
            "trust_level": a.trust_level,
            "max_tokens": a.max_tokens,
        },
    }


@router.post("")
async def mcp_endpoint(
    request: Request,
    api_key: str = Depends(require_api_key),
) -> dict:
    """JSON-RPC 2.0 entrypoint for MCP method dispatch."""
    body = await request.json()
    if not isinstance(body, dict):
        return _jsonrpc_error(None, -32700, "parse error: body must be an object")
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return _jsonrpc_result(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "a2a-gateway-mcp-bridge",
                    "version": "1.0.0",
                },
            },
        )

    if method == "tools/list":
        return _jsonrpc_result(
            req_id,
            {
                "tools": [_tool_for_agent(a["agent_id"]) for a in list_agents()],
            },
        )

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not tool_name or not isinstance(tool_name, str):
            return _jsonrpc_error(req_id, -32602, "invalid params: missing 'name'")
        agent = get_agent(tool_name)
        if not agent:
            return _jsonrpc_error(req_id, -32601, f"tool not found: {tool_name}")
        prompt = arguments.get("prompt")
        if not prompt or not isinstance(prompt, str):
            return _jsonrpc_error(req_id, -32602, "invalid params: 'arguments.prompt' is required")
        caller_id = arguments.get("caller_id") or "mcp-client"
        # Trust level check
        if agent.trust_level == "elevated":
            trust_header = request.headers.get("X-Trust-Level", "standard")
            if trust_header != "elevated":
                return _jsonrpc_error(
                    req_id,
                    -32603,
                    f"agent {tool_name} requires elevated trust; got {trust_header}",
                )
        # Rate limit
        try:
            rate_limiter.check(caller_id)
        except HTTPException as exc:
            return _jsonrpc_error(req_id, -32429, exc.detail)

        # Audit + invoke (synchronous over MCP)
        job_id = uuid.uuid4().hex
        await emit_audit_event(
            category="agent.dispatch",
            event="invoke_start",
            agent_id=tool_name,
            caller_id=caller_id,
            job_id=job_id,
            trust_level=agent.trust_level,
            extra={"channel": "mcp", "prompt_len": len(prompt)},
        )

        try:
            result = await invoke_agent(tool_name, prompt, arguments.get("context"))
        except Exception as exc:  # noqa: BLE001
            await emit_audit_event(
                category="agent.dispatch",
                event="invoke_error",
                agent_id=tool_name,
                caller_id=caller_id,
                job_id=job_id,
                trust_level=agent.trust_level,
                extra={"channel": "mcp", "error": str(exc)},
            )
            return _jsonrpc_error(req_id, -32603, f"agent invocation failed: {exc}")

        await emit_audit_event(
            category="agent.dispatch",
            event="invoke_complete" if result.success else "invoke_failed",
            agent_id=tool_name,
            caller_id=caller_id,
            job_id=job_id,
            trust_level=agent.trust_level,
            extra={
                "channel": "mcp",
                "success": result.success,
                "return_code": result.return_code,
            },
        )

        return _jsonrpc_result(
            req_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": result.output if result.output else (result.error or "(no output)"),
                    }
                ],
                "isError": not result.success,
            },
        )

    return _jsonrpc_error(req_id, -32601, f"method not found: {method}")
