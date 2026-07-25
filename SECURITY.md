# Security Policy

## Reporting a vulnerability

Report vulnerabilities through
[GitHub Security Advisories](https://github.com/bulletproofsoftware-ai/bulletproof-a2a-gateway/security/advisories/new)
rather than a public issue. Please include a description, reproduction steps,
and the impact you believe it has. We aim to acknowledge within 5 business days.

Do not include live credentials in a report.

## Supported versions

The `main` branch receives security fixes. Older tags do not.

## What this service does

The gateway accepts an HTTP request and, on the strength of that request, runs a
command on the host. That makes it a privileged component. The controls below
are the ones it actually implements — read them before exposing it.

### Authentication

Every route except `/health` and `/.well-known/agent.json` requires a valid
`X-API-Key`. Keys come from the comma-separated `API_KEYS` environment
variable.

- With `API_KEYS` unset, authenticated routes return **500, not 200** — the
  service fails closed rather than opening up.
- Keys are compared for exact membership. There is no key hierarchy, no
  expiry, and no per-key scoping beyond the trust level described below.
- Rotate by changing `API_KEYS` and restarting.

### Trust levels

Each registry entry declares `trust_level`:

- `standard` — any caller with a valid API key may invoke it.
- `elevated` — additionally requires the `X-Trust-Level: elevated` header.

Enforced identically on the REST invoke path and the MCP `tools/call` path.
Put any agent that writes files, runs builds, or mutates state behind
`elevated`.

Note this is a coarse control: the header is supplied by the caller, so it
distinguishes *deliberate* elevated invocation from accidental invocation, and
pairs with network-level restrictions — it is not a substitute for them. If you
need per-key authorization, terminate that in front of the gateway.

### Command injection

`A2A_INVOKER_TEMPLATE` is tokenised with `shlex.split` **before** `{agent_id}`,
`{prompt}`, and `{context}` are substituted, and the result is passed to
`create_subprocess_exec` — never to a shell. A prompt containing spaces,
quotes, `;`, `$(...)`, or backticks is therefore always exactly one argument
and cannot introduce another. `tests/test_invoker.py` covers this directly.

Substitution is single-pass, so a value is never rescanned for further
placeholders: a prompt containing the literal text `{context}` is passed
through unchanged rather than expanded.

Two things remain the operator's responsibility:

- **Don't wrap the template in a shell.** A template like
  `sh -c '... {prompt}'` reintroduces every risk the design removes.
- **Terminate your flags with `--`** when the prompt is positional, so a prompt
  beginning with a dash is treated as data rather than an option by the target
  program:

  ```bash
  A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} -- {prompt}'
  ```

  Without it, a caller can steer the invoked program's own flags. The gateway
  cannot do this for you — only the template author knows where that
  program's options end.

### Rate limiting

`RATE_LIMIT_RPM` (default 60) caps requests per `caller_id` per minute. The
window is in-process, so with multiple workers the effective limit is
per-worker. `caller_id` is caller-supplied and unauthenticated, so treat the
limiter as protection against runaway clients, not against a determined
attacker — for that, rate-limit at the ingress.

### Audit

Every invocation start and completion POSTs a JSON event to
`A2A_AUDIT_EVENT_ROUTER_URL`. Emission is best-effort and never blocks an
invocation, which means **an attacker who can reach the sink can suppress
audit records without stopping traffic**. Send audit to a sink you control, on
a network path the caller cannot influence.

Events contain the caller id, agent id, job id, trust level, and prompt
*length* — not prompt content.

### Deployment expectations

- Terminate TLS in front of the gateway; it speaks plain HTTP.
- Do not expose it directly to the internet. It is designed to sit on a trusted
  network behind an authenticating proxy.
- Run it as a non-root user. The bundled `Dockerfile` runs as uid 10001.
- Jobs and rate-limit state are in-memory: they are lost on restart and are not
  shared across replicas.
- Job results are retained in memory for the process lifetime and are readable
  by any valid API key that knows the job id. Job ids are UUID4.

## Known limitations

These are design limits, not planned work:

- No per-key scoping, expiry, or revocation list.
- No persistence for jobs or rate-limit state.
- `caller_id` is self-asserted.
- The `allowed_tools` field in the registry is advisory metadata published in
  discovery responses; the gateway does not enforce it. Enforcement belongs to
  the agent runtime you point the invoker at.
