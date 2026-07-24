# How to Use — bulletproof-a2a-gateway

This is the complete, real endpoint reference, taken directly from
[`src/main.py`](../src/main.py) and [`src/adapters/mcp_bridge.py`](../src/adapters/mcp_bridge.py).
Examples use `http://localhost:8100` (the `.env.example` port) — adjust to your run port.

## Authentication

All authenticated endpoints require the header:

```
X-API-Key: <one of the comma-separated keys in API_KEYS>
```

- Missing header → `401 Missing X-API-Key header`
- No keys configured on the server → `500 No API keys configured on server`
- Unknown key → `403 Invalid API key`

Public (no-auth) endpoints: `GET /health` and `GET /.well-known/agent.json`.

---

## REST API

### `GET /health` — health check (public)

```bash
curl -s http://localhost:8100/health
```

```json
{
  "status": "healthy",
  "service": "a2a-gateway",
  "version": "1.0.0",
  "agent_count": 15,
  "timestamp": "2026-07-24T19:00:00.000000+00:00"
}
```

> The `version` field is hard-coded to `"1.0.0"` in the health handler, while the FastAPI app
> declares `version="1.1.0"`. See the known-gap note in [ADMINISTRATOR.md](ADMINISTRATOR.md).

### `GET /api/v1/agents` — discover agents (auth)

```bash
curl -s http://localhost:8100/api/v1/agents -H "X-API-Key: <key>"
```

```json
{
  "count": 15,
  "agents": [
    {
      "agent_id": "conductor-architect",
      "description": "Designs system architecture, component boundaries, ...",
      "allowed_tools": ["Read", "Glob", "Grep", "Bash"],
      "max_tokens": 32768,
      "trust_level": "elevated",
      "externally_callable": true
    }
    // ... 14 more
  ]
}
```

### `POST /api/v1/agents/{agent_id}/invoke` — invoke an agent (auth, async)

Returns `202 Accepted` with a `job_id`. The invocation runs in the background; poll the job for
the result.

Request body:

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `prompt` | string | yes | 1–100000 chars |
| `context` | string | no | ≤ 100000 chars (prepended to the prompt) |
| `caller_id` | string | yes | 1–256 chars — used for rate-limiting and audit |

```bash
curl -s -X POST http://localhost:8100/api/v1/agents/conductor-qa/invoke \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{
        "prompt": "Review the auth module for missing edge cases",
        "caller_id": "ci-pipeline-42"
      }'
```

```json
{ "job_id": "1f0e...uuid", "status": "pending" }
```

Errors:
- `404` — `Agent '<id>' not found. Use GET /api/v1/agents to discover available agents.`
- `429` — `Rate limit exceeded: 60 requests per 60s` (per `caller_id`).

> **Elevated agents over REST.** For agents with `trust_level: elevated`, the intended contract
> is an additional `X-Trust-Level: elevated` header. Note the REST handler currently does **not**
> enforce this (the check is stubbed) — see the known-gap note in
> [ADMINISTRATOR.md](ADMINISTRATOR.md). The **MCP** path *does* enforce it.

### `GET /api/v1/jobs/{job_id}` — poll a job (auth)

```bash
curl -s http://localhost:8100/api/v1/jobs/<job_id> -H "X-API-Key: <key>"
```

```json
{
  "job_id": "1f0e...uuid",
  "agent_id": "conductor-qa",
  "caller_id": "ci-pipeline-42",
  "status": "completed",
  "result": "…agent stdout…",
  "error": null,
  "created_at": "2026-07-24T19:00:00+00:00",
  "completed_at": "2026-07-24T19:00:37+00:00"
}
```

`status` is one of `pending` → `running` → `completed` | `failed`. On failure, `error` holds the
message and `result` may hold partial stdout. `404` if the `job_id` is unknown.

> **Jobs are in-memory.** The job store is a process-local dict; jobs do not survive a restart
> and are not shared across replicas.

### `GET /.well-known/agent.json` — A2A agent card (public)

Standard A2A discovery card. No auth. Advertises the gateway, its protocol version, the
`api_key` auth scheme (header `X-API-Key`), a 60 rpm rate limit, and one card per agent with its
invoke endpoint.

```bash
curl -s http://localhost:8100/.well-known/agent.json
```

---

## MCP Bridge

The bridge exposes the same 15 agents as MCP tools over JSON-RPC 2.0 at **`POST /mcp`**. It uses
the **same `X-API-Key`** authentication as REST. Unlike REST, MCP invocation is **synchronous** —
`tools/call` waits for the agent and returns the output inline.

Supported methods: `initialize`, `tools/list`, `tools/call`.

### `initialize`

```bash
curl -s -X POST http://localhost:8100/mcp \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}'
```

```json
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": { "tools": { "listChanged": false } },
    "serverInfo": { "name": "a2a-gateway-mcp-bridge", "version": "1.0.0" }
  }
}
```

### `tools/list`

Returns one tool per agent. Each tool's `name` is the `agent_id`, with an `inputSchema`
requiring `prompt` + `caller_id` (and optional `context`), plus `annotations` carrying
`trust_level` and `max_tokens`.

```bash
curl -s -X POST http://localhost:8100/mcp \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

### `tools/call`

```bash
curl -s -X POST http://localhost:8100/mcp \
  -H "X-API-Key: <key>" -H "Content-Type: application/json" \
  -d '{
        "jsonrpc":"2.0","id":3,"method":"tools/call",
        "params":{
          "name":"conductor-research",
          "arguments":{
            "prompt":"Compare httpx vs aiohttp for async clients",
            "caller_id":"mcp-demo"
          }
        }
      }'
```

```json
{
  "jsonrpc": "2.0", "id": 3,
  "result": {
    "content": [ { "type": "text", "text": "…agent output…" } ],
    "isError": false
  }
}
```

`caller_id` defaults to `"mcp-client"` if omitted (still rate-limited and audited).

**MCP error codes** (JSON-RPC `error.code`):

| Code | Meaning |
|------|---------|
| `-32700` | Parse error — body is not a JSON object |
| `-32601` | Method not found, or `tool not found: <name>` |
| `-32602` | Invalid params — missing `name` or `arguments.prompt` |
| `-32603` | Trust check failed, or agent invocation raised |
| `-32429` | Rate limit exceeded (non-standard code used by this bridge) |

### Elevated trust over MCP

For `elevated` agents, the caller **must** send `X-Trust-Level: elevated`, else:

```json
{ "jsonrpc":"2.0","id":3,
  "error":{ "code":-32603,
    "message":"agent conductor-builder requires elevated trust; got standard" } }
```

```bash
curl -s -X POST http://localhost:8100/mcp \
  -H "X-API-Key: <key>" -H "X-Trust-Level: elevated" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call",
       "params":{"name":"conductor-builder",
                 "arguments":{"prompt":"Implement the parser","caller_id":"mcp-demo"}}}'
```

---

## Audit events

Every invoke (start / complete / failed / error) fires a best-effort audit event to an external
event-router (default `http://host.docker.internal:8085/events`, override with
`A2A_AUDIT_EVENT_ROUTER_URL`). Audit failures are logged but **never** block or fail an
invocation. Event payloads carry `category`, `event`, `source: "a2a-gateway"`, `actor`
(the `caller_id`), `agent_id`, `job_id`, `trust_level`, and a `channel` of `rest` or `mcp`.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
