# Overview — bulletproof-a2a-gateway

`bulletproof-a2a-gateway` is a [FastAPI](https://fastapi.tiangolo.com/) service that lets
agents (and external callers) invoke other agents' capabilities **safely**. It authenticates
every caller, enforces per-caller rate limits, audits every invocation, and bridges to the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so the same agents are
reachable from MCP-aware clients (Claude Code, Claude Desktop, the MCP Inspector).

**It is agent-runtime agnostic.** The gateway does not bake in any particular agent CLI or
framework. You declare your agents in a YAML registry and tell the gateway how to run one with
a configurable command template — the invoker is pluggable.

## What it actually does

| Capability | Where it lives | Notes |
|-----------|----------------|-------|
| **Capability registry** | `src/agents.py` + `registry/capabilities.yaml` | YAML is the source of truth. Agents load at import time; only entries with `externally_callable: true` are reachable. |
| **Authenticated invocation** | `src/auth.py` | Callers present an `X-API-Key` header. Keys come from the `API_KEYS` env var (comma-separated). |
| **Rate limiting** | `src/rate_limiter.py` | In-memory sliding-window limiter, keyed by `caller_id`. Limit is read from `RATE_LIMIT_RPM` (default 60 requests / 60 s). |
| **Audit** | `src/audit.py` | Every invoke/complete/fail fires a best-effort event to an external HTTP sink. Never blocks the invocation. |
| **Async job dispatch** | `src/main.py` | REST invocations run as FastAPI background tasks; callers poll a `job_id`. |
| **Agent execution** | `src/invoker.py` | Pluggable executor (`A2A_INVOKER_EXECUTOR`): `subprocess` (default) runs a configurable command template as an async subprocess; `echo` returns the prompt without executing anything. Timeout is read from `A2A_INVOKER_TIMEOUT_S` (default 300s). |
| **MCP bridge** | `src/adapters/mcp_bridge.py` | JSON-RPC 2.0 over HTTP at `POST /mcp` — `initialize`, `tools/list`, `tools/call`. Each agent becomes one MCP tool. |

## Architecture at a glance

```
                          X-API-Key
  external caller ───────────────────────►  ┌─────────────────────────┐
  (REST or MCP client)                       │  A2A Gateway (FastAPI)  │
                                             │                          │
                                             │  auth ─► rate_limit ─►   │
                                             │  agents registry ─►      │
                                             │  invoker (pluggable) ─►  │──► your agent runtime
                                             │  audit (best-effort) ────┼──► HTTP event sink
                                             └─────────────────────────┘
```

- **Two entry surfaces, one core.** REST (`/api/v1/...`) and MCP (`/mcp`) both funnel through
  the same auth → rate-limit → registry lookup → invoker → audit path.
- **REST is asynchronous** (returns a `job_id`, HTTP `202`); **MCP is synchronous** (waits for
  the agent and returns the result inline).
- **Trust levels.** Agents are `standard` or `elevated`. Elevated agents require an additional
  `X-Trust-Level: elevated` header, enforced on both the REST invoke path (`403`) and the MCP
  `tools/call` path (JSON-RPC `-32603`).
- **The invoker is pluggable.** `A2A_INVOKER_TEMPLATE` is a command line with `{agent_id}`,
  `{prompt}`, and `{context}` placeholders. It is tokenised with `shlex.split` *before*
  substitution and run via `create_subprocess_exec` — never a shell — so a prompt can never
  inject extra arguments. If `{prompt}` is omitted, the prompt is written to the command's
  stdin instead.

## The exposed agents

`registry/capabilities.yaml` ships **three example agents**, all `externally_callable: true`,
meant to be replaced with your own:

`example-reviewer` (standard) · `example-researcher` (standard) · `example-builder` (elevated)

Each entry declares an `allowed_tools` list (advisory — published in discovery, not enforced by
the gateway) and a `max_tokens` budget.

Claude Code's conductor agent suite is one worked example of wiring a real runtime behind the
gateway — see [`examples/`](../examples/) — but it is entirely optional. The gateway itself has
no dependency on the `claude` CLI or any particular agent framework.

## What this repo is NOT

- It does **not** bundle or vendor any agents — it invokes whatever `A2A_INVOKER_TEMPLATE`
  points at, which is the operator's choice.
- It does **not** persist jobs. The job store is an in-memory dict (`_jobs`); jobs are lost on
  restart.
- It does **not** ship a database. Audit events are POSTed to an HTTP sink
  (`A2A_AUDIT_EVENT_ROUTER_URL`); there is no local audit database.

## Where to go next

- [INSTALL.md](INSTALL.md) — install and run (local + Docker).
- [HOW-TO-USE.md](HOW-TO-USE.md) — every REST + MCP endpoint with real request/response shapes.
- [ADMINISTRATOR.md](ADMINISTRATOR.md) — configuration, registry management, trust levels, design limits.
- [SBOM.md](SBOM.md) — dependency inventory and license posture.
- [scan/scan-report.md](scan/scan-report.md) — security scan results (0 critical / 0 high).

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
