# Administrator Guide — bulletproof-a2a-gateway

Operational reference for running, configuring, and securing the gateway.

## Configuration (environment variables)

The gateway is env-driven. `.env` is **not** auto-loaded by the application — export the vars
into the process environment (see [INSTALL.md](INSTALL.md)).

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `API_KEYS` | *(empty)* | `src/auth.py` | **Required.** Comma-separated API keys callers present via `X-API-Key`. With none set, every authenticated route returns `500 No API keys configured on server`. |
| `HOST` | `0.0.0.0` | `.env.example` | Bind address (pass to `uvicorn --host`). |
| `PORT` | `8100` | `.env.example`, `uvicorn` | Listen port. The Dockerfile exposes and serves on the same port. |
| `RATE_LIMIT_RPM` | `60` | `src/rate_limiter.py` | Per-caller requests per minute. Read at import; restart to change. Non-numeric or `< 1` values log a warning and fall back to 60. |
| `A2A_REGISTRY_PATH` | `registry/capabilities.yaml` | `src/agents.py` | Override the agent registry file location. |
| `A2A_INVOKER_EXECUTOR` | `subprocess` | `src/invoker.py` | Which executor runs an agent: `subprocess` or `echo`. |
| `A2A_INVOKER_TEMPLATE` | *(empty)* | `src/invoker.py` | **Required for `subprocess`.** The command line that runs an agent. See [Agent execution model](#agent-execution-model). |
| `A2A_INVOKER_TIMEOUT_S` | `300` | `src/invoker.py` | Seconds before an invocation is killed. Invalid values fall back to 300. |
| `A2A_AUDIT_EVENT_ROUTER_URL` | `http://localhost:8085/events` | `src/audit.py` | Where audit events are POSTed. |
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
| `agent_id` | string | — | The identifier callers use. Substituted into `{agent_id}` in the invoker template. |
| `description` | string | — | Human-readable; surfaced in discovery + MCP `tools/list`. |
| `externally_callable` | bool | `true` | If `false`, the agent is **skipped** at load and is unreachable. This is the outside-world allowlist. |
| `trust_level` | `standard`\|`elevated` | `standard` | `elevated` additionally requires `X-Trust-Level: elevated`. |
| `allowed_tools` | list | `[]` | Advisory metadata published in discovery. **Not enforced by the gateway** — enforcement belongs to your agent runtime. |
| `max_tokens` | int | `16384` | Advisory budget surfaced in discovery/MCP annotations. |

The shipped `registry/capabilities.yaml` contains **three example entries** to be replaced with
your own agents. A larger real-world registry (15 agents for the Claude Code conductor plugin
suite) ships as [`examples/capabilities.conductor.yaml`](../examples/capabilities.conductor.yaml)
and is not loaded unless you point `A2A_REGISTRY_PATH` at it.

## Trust levels

- **standard** — invocable by any caller with a valid `X-API-Key`.
- **elevated** — additionally requires `X-Trust-Level: elevated`.

Enforced on **both** paths: REST returns `403`, MCP returns JSON-RPC `-32603`. Put any agent
that writes files or mutates state behind `elevated`. Because the header is caller-supplied,
treat it as separating deliberate from accidental elevated use, not as authorization — pair it
with network restrictions.

## Rate limiting

`src/rate_limiter.py` is an in-memory sliding-window limiter keyed by `caller_id`, sized by
`RATE_LIMIT_RPM` requests per 60 s. Because state is in-process:

- Limits are **per replica**, not global. Behind a load balancer, effective limits scale with
  replica count.
- State resets on restart.
- A caller that omits/reuses `caller_id` shares a bucket. Callers should send a stable, unique
  `caller_id`.

## Audit / observability

Audit events are POSTed to `A2A_AUDIT_EVENT_ROUTER_URL`. Any HTTP endpoint that accepts a JSON
body works; [bulletproof-event-router](https://github.com/bulletproofsoftware-ai/bulletproof-event-router)
is one such sink. Emission is best-effort with a 1.5 s timeout; failures are logged at WARNING
and never affect invocations. With no sink reachable, audit events are effectively dropped
(with warnings in the gateway log).

Events carry the caller id, agent id, job id, trust level, and prompt *length* — not prompt
content.

Application logs go to stdout at INFO (`logging.basicConfig` in `src/main.py`).

## Agent execution model

The gateway is agent-runtime agnostic. An **executor** turns a request into an invocation,
selected with `A2A_INVOKER_EXECUTOR`:

- **`subprocess`** (default) — renders `A2A_INVOKER_TEMPLATE` and runs it as an async
  subprocess with an `A2A_INVOKER_TIMEOUT_S` (default 300 s) timeout.
- **`echo`** — returns the rendered prompt without executing anything. Use it to smoke-test
  auth, rate limiting, discovery, and the MCP bridge before an agent runtime exists.

`A2A_INVOKER_TEMPLATE` is a command line containing any of `{agent_id}`, `{prompt}`, and
`{context}`:

```bash
A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} --prompt {prompt}'
```

The template is tokenised with `shlex.split` **before** substitution and executed via
`create_subprocess_exec`, never through a shell — a prompt cannot inject extra arguments.
Omitting `{prompt}` writes the prompt to the command's stdin instead.

See [`examples/README.md`](../examples/README.md) for worked configurations, including the
Claude Code conductor agents and how to register a custom executor in Python.

Operational implications:

- Whatever binary your template names **must be installed and on `PATH`** in the gateway's
  runtime environment. The Docker image contains only the gateway.
- Each invocation spawns a subprocess — concurrency and host resources bound throughput.
- Timeouts return a `failed` job / MCP error.

## Security posture

- **Non-root container.** The image runs as `appuser` (uid 10001).
- **Least-privilege CI.** GitHub Actions workflow uses `permissions: contents: read` and pins
  actions to commit SHAs.
- **No secrets in the tree.** `gitleaks` scan is clean (see [scan/scan-report.md](scan/scan-report.md)).
- **Bring your own transport security.** The gateway speaks plain HTTP; terminate TLS at a
  reverse proxy / ingress in production. API keys are bearer-equivalent — protect them in
  transit and at rest.

## Design limits

These are properties of the current design, not defects awaiting a fix. Plan around them:

1. **Jobs are in-memory and single-process.** No persistence, no cross-replica sharing. A
   restart loses in-flight and completed job records.
2. **Rate-limit state is per-process.** Behind a load balancer the effective limit is
   `RATE_LIMIT_RPM × replicas`. Enforce a global limit at the ingress if you need one.
3. **`caller_id` is self-asserted.** It identifies a caller for rate-limiting and audit
   correlation; it is not authenticated.
4. **API keys are unscoped.** Any valid key reaches any `standard` agent, and any valid key
   plus `X-Trust-Level: elevated` reaches any `elevated` agent. There is no per-key scoping,
   expiry, or revocation list. Terminate finer-grained authorization in front of the gateway.
5. **`allowed_tools` is advisory.** The gateway publishes it in discovery but does not enforce
   it; your agent runtime must.
6. **Job results are readable by any valid key** that knows the job id (UUID4).

Changes to `RATE_LIMIT_RPM`, the registry, and the invoker configuration are all read at import
time — **restart the gateway** for them to take effect.

## Prior known gaps, now closed

Earlier releases documented these; they are fixed as of the current `main`:

- The port story is unified on **8100** across `.env.example`, README, Dockerfile, and registry.
- `RATE_LIMIT_RPM` is read by the limiter.
- `AUDIT_DB_PATH` is removed — no local DB was ever written and audit is HTTP-only.
- Elevated trust is enforced on the REST invoke path as well as MCP.
- `/health.version` reports the same version the app declares.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
