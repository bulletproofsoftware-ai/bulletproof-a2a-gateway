# Administrator Guide — bulletproof-a2a-gateway

Operational reference for running, configuring, and securing the gateway.

## Configuration (environment variables)

The gateway is env-driven. `.env` is **not** auto-loaded by the application — export the vars
into the process environment (see [INSTALL.md](INSTALL.md)).

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `API_KEYS` | *(empty)* | `src/auth.py` | **Required.** Comma-separated API keys callers present via `X-API-Key`. With none set, every authenticated route returns `500 No API keys configured on server`. |
| `HOST` | `0.0.0.0` | `.env.example` | Bind address (pass to `uvicorn --host`). |
| `PORT` | `8100` (`.env`) / `8420` (Docker) | `.env.example`, `uvicorn` | Listen port. See the port-mismatch note below. |
| `RATE_LIMIT_RPM` | `60` | `.env.example` | Intended per-key rate limit. **Note:** the limiter in `src/rate_limiter.py` is currently hard-coded to `max_requests=60, window_seconds=60` and does **not** read this env var (see known gaps). |
| `AUDIT_DB_PATH` | `./data/audit.db` | `.env.example` | Intended audit DB path. **Note:** the current audit implementation emits HTTP events to an event-router and does not write this DB (see known gaps). |
| `A2A_REGISTRY_PATH` | `registry/capabilities.yaml` | `src/agents.py` | Override the agent registry file location. |
| `A2A_AUDIT_EVENT_ROUTER_URL` | `http://host.docker.internal:8085/events` | `src/audit.py` | Where audit events are POSTed. |
| `A2A_AUDIT_TIMEOUT_S` | `1.5` | `src/audit.py` | Audit HTTP timeout (seconds). Best-effort; failures never block invokes. |

### Generating API keys

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set multiple keys by comma-separating: `API_KEYS=key1,key2,key3`. Keys are trimmed of
whitespace on load. There is no per-key identity or scoping beyond the trust-level mechanism
below — a valid key can invoke any `standard` agent.

## Managing the agent registry

`registry/capabilities.yaml` is the **source of truth**. To add, remove, or change an agent,
edit the YAML and **restart** the gateway (the registry loads once at import time in
`src/agents.py`). Do not edit `src/agents.py` for registry changes.

Each agent entry supports:

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `agent_id` | string | — | The conductor agent id (e.g. `conductor-qa`). The invoker strips a leading `conductor-` and calls `claude --agent conductor:<name>`. |
| `description` | string | — | Human-readable; surfaced in discovery + MCP `tools/list`. |
| `externally_callable` | bool | `true` | If `false`, the agent is **skipped** at load and is unreachable. This is the outside-world allowlist. |
| `trust_level` | `standard`\|`elevated` | `standard` | `elevated` requires `X-Trust-Level: elevated` (enforced on the MCP path; see gaps for REST). |
| `allowed_tools` | list | `[]` | Tools the agent may use in gateway mode (a subset of its local surface). |
| `max_tokens` | int | `16384` | Token budget surfaced in discovery/MCP annotations. |

The shipped registry declares **15** agents, all `externally_callable: true`. Six are
`elevated`: `conductor-architect`, `conductor-builder`, `conductor-refactor`,
`conductor-database`, `conductor-devops`, `conductor-compliance`.

## Trust levels

- **standard** — invocable by any caller with a valid `X-API-Key`.
- **elevated** — additionally requires `X-Trust-Level: elevated`. The **MCP bridge enforces
  this** (returns JSON-RPC `-32603` on mismatch). See the REST gap below.

## Rate limiting

`src/rate_limiter.py` is an in-memory sliding-window limiter keyed by `caller_id`
(60 requests / 60 s). Because state is in-process:

- Limits are **per replica**, not global. Behind a load balancer, effective limits scale with
  replica count.
- State resets on restart.
- A caller that omits/reuses `caller_id` shares a bucket. Callers should send a stable, unique
  `caller_id`.

## Audit / observability

Audit events go to an external **event-router** (`A2A_AUDIT_EVENT_ROUTER_URL`). Emission is
best-effort with a 1.5 s timeout; failures are logged at WARNING and never affect invocations.
If you run the SOC/governance stack, point this at its ingest endpoint; otherwise audit events
are effectively dropped (with warnings in the gateway log).

Application logs go to stdout at INFO (`logging.basicConfig` in `src/main.py`).

## Agent execution model

Invocation shells out to the local `claude` CLI as an async subprocess with a **300 s** timeout
(`src/invoker.py`). Operational implications:

- The **`claude` CLI must be installed and on `PATH`** in the gateway's runtime environment,
  with access to the `conductor:*` agents. The Docker image does **not** include it.
- Each invocation spawns a subprocess — concurrency and host resources bound throughput.
- Timeouts return a `failed` job / MCP error after 300 s.

## Security posture

- **Non-root container.** The image runs as `appuser` (uid 10001).
- **Least-privilege CI.** GitHub Actions workflow uses `permissions: contents: read` and pins
  actions to commit SHAs.
- **No secrets in the tree.** `gitleaks` scan is clean (see [scan/scan-report.md](scan/scan-report.md)).
- **Bring your own transport security.** The gateway speaks plain HTTP; terminate TLS at a
  reverse proxy / ingress in production. API keys are bearer-equivalent — protect them in
  transit and at rest.

## Known gaps (documented, not silently patched)

These are real discrepancies between the shipped config/README and the implementation. They are
called out here rather than "fixed" so operators aren't surprised, and so a maintainer decides
the intended behaviour:

1. **Port mismatch.** `.env.example` + README use **8100**; `Dockerfile`, its `HEALTHCHECK`, and
   `registry/capabilities.yaml` (`gateway_port`) use **8420**. Choose one explicitly when
   launching `uvicorn`.
2. **`RATE_LIMIT_RPM` is inert.** The limiter is hard-coded to 60/60s and does not read
   `RATE_LIMIT_RPM`. To change the limit today you must edit `src/rate_limiter.py`.
3. **`AUDIT_DB_PATH` is inert.** No local audit DB is written; audit is HTTP-only to the
   event-router. The `data/` dir and `AUDIT_DB_PATH` are vestigial in the current code.
4. **Elevated trust is not enforced on the REST invoke path.** In `src/main.py` the elevated-agent
   branch is a stub (`pass`) — a valid API key can invoke an `elevated` agent over REST without
   `X-Trust-Level: elevated`. The **MCP** path enforces it correctly. If you rely on the trust
   gate, restrict access at the network layer for the REST endpoint until this is closed.
5. **Health `version` is hard-coded** to `"1.0.0"` while the app declares `"1.1.0"`. Cosmetic,
   but don't rely on `/health.version` for release tracking.
6. **Jobs are in-memory and single-process.** No persistence, no cross-replica sharing.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
