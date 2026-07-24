# Overview — bulletproof-a2a-gateway

`bulletproof-a2a-gateway` is a [FastAPI](https://fastapi.tiangolo.com/) service that lets
agents (and external callers) invoke other agents' capabilities **safely**. It authenticates
every caller, enforces per-caller rate limits, audits every invocation, and bridges to the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so the same agents are
reachable from MCP-aware clients (Claude Code, Claude Desktop, the MCP Inspector).

The agents it exposes are **conductor agents** — a fixed set declared in
[`registry/capabilities.yaml`](../registry/capabilities.yaml). When invoked, the gateway
shells out to the local `claude` CLI (`claude -p "<prompt>" --agent conductor:<name>`) and
returns the agent's output.

## What it actually does

| Capability | Where it lives | Notes |
|-----------|----------------|-------|
| **Capability registry** | `src/agents.py` + `registry/capabilities.yaml` | YAML is the source of truth. Agents load at import time; only entries with `externally_callable: true` are reachable. |
| **Authenticated invocation** | `src/auth.py` | Callers present an `X-API-Key` header. Keys come from the `API_KEYS` env var (comma-separated). |
| **Rate limiting** | `src/rate_limiter.py` | In-memory sliding-window limiter, keyed by `caller_id`. Default 60 requests / 60 s. |
| **Audit** | `src/audit.py` | Every invoke/complete/fail fires a best-effort event to an external event-router. Never blocks the invocation. |
| **Async job dispatch** | `src/main.py` | REST invocations run as FastAPI background tasks; callers poll a `job_id`. |
| **Agent execution** | `src/invoker.py` | Runs the `claude` CLI as an async subprocess (300 s timeout). |
| **MCP bridge** | `src/adapters/mcp_bridge.py` | JSON-RPC 2.0 over HTTP at `POST /mcp` — `initialize`, `tools/list`, `tools/call`. Each agent becomes one MCP tool. |

## Architecture at a glance

```
                          X-API-Key
  external caller ───────────────────────►  ┌─────────────────────────┐
  (REST or MCP client)                       │  A2A Gateway (FastAPI)  │
                                             │                          │
                                             │  auth ─► rate_limit ─►   │
                                             │  agents registry ─►      │
                                             │  invoker (claude CLI) ─► │──► conductor agent
                                             │  audit (best-effort) ────┼──► event-router
                                             └─────────────────────────┘
```

- **Two entry surfaces, one core.** REST (`/api/v1/...`) and MCP (`/mcp`) both funnel through
  the same auth → rate-limit → registry lookup → invoker → audit path.
- **REST is asynchronous** (returns a `job_id`, HTTP `202`); **MCP is synchronous** (waits for
  the agent and returns the result inline).
- **Trust levels.** Agents are `standard` or `elevated`. Elevated agents require an additional
  `X-Trust-Level: elevated` header. (See the known-gap note in
  [ADMINISTRATOR.md](ADMINISTRATOR.md) — the REST path's elevated check is incomplete.)

## The exposed agents

`registry/capabilities.yaml` declares **15 conductor agents**, all `externally_callable: true`:

`conductor-architect` · `conductor-builder` · `conductor-qa` · `conductor-code-reviewer` ·
`conductor-doc-gen` · `conductor-bug-find` · `conductor-refactor` · `conductor-research` ·
`conductor-database` · `conductor-devops` · `conductor-api-design` · `conductor-api-docs` ·
`conductor-compliance` · `conductor-performance` · `conductor-observability`

Six of these are `elevated` (architect, builder, refactor, database, devops, compliance); the
rest are `standard`. Each entry declares an `allowed_tools` list and a `max_tokens` budget.

## What this repo is NOT

- It does **not** bundle or vendor the conductor agents — it invokes them via the local
  `claude` CLI, which must be installed and on `PATH` at runtime.
- It does **not** persist jobs. The job store is an in-memory dict (`_jobs`); jobs are lost on
  restart.
- It does **not** ship a database. `AUDIT_DB_PATH` appears in `.env.example` but the current
  audit implementation emits HTTP events to an event-router rather than writing a local DB
  (documented as a config-vs-implementation gap in [ADMINISTRATOR.md](ADMINISTRATOR.md)).

## Where to go next

- [INSTALL.md](INSTALL.md) — install and run (local + Docker).
- [HOW-TO-USE.md](HOW-TO-USE.md) — every REST + MCP endpoint with real request/response shapes.
- [ADMINISTRATOR.md](ADMINISTRATOR.md) — configuration, registry management, trust levels, known gaps.
- [SBOM.md](SBOM.md) — dependency inventory and license posture.
- [scan/scan-report.md](scan/scan-report.md) — security scan results (0 critical / 0 high).

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
