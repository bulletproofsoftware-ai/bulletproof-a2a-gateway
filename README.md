# bulletproof-a2a-gateway

**An agent-to-agent gateway: authenticated, rate-limited, audited invocation between agents.**

![bulletproof-a2a-gateway — overview](docs/media/infographic.png)

> 📚 **Docs:** [`docs/`](docs/) (overview, install, how-to-use, administrator, SBOM, security scan).
> 🎬 **Media:** slide deck, explainer video, and briefing doc in [`media/`](media/).

`bulletproof-a2a-gateway` is a FastAPI service that lets agents (and external
callers) invoke other agents' capabilities safely. It authenticates callers,
enforces per-caller rate limits, audits every invocation, and bridges to MCP so
an agent's capabilities can be exposed and called over a uniform API.

**It is agent-runtime agnostic.** You register your own agents in a YAML
registry and tell the gateway how to run them with a command template. Nothing
about a particular CLI or agent framework is baked in.

## What it does

- **Capability registry** — you declare your agents in
  [`registry/capabilities.yaml`](registry/capabilities.yaml). Agents not listed
  are not reachable.
- **Authenticated invocation** — callers present an `X-API-Key`; write-capable
  agents can be gated further behind `X-Trust-Level: elevated`.
- **Rate limiting** — per-caller requests/minute, set by `RATE_LIMIT_RPM`.
- **Audit** — every invocation POSTs a JSON event to a sink of your choosing.
- **MCP bridge** — every registered agent is also exposed as an MCP tool.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # set API_KEYS, then A2A_INVOKER_TEMPLATE
uvicorn src.main:app --host 0.0.0.0 --port 8100
```

Try it without wiring up a real agent runtime first — the `echo` executor
returns the prompt instead of running anything:

```bash
API_KEYS=dev-key A2A_INVOKER_EXECUTOR=echo \
  uvicorn src.main:app --port 8100

curl -s http://localhost:8100/health
curl -s http://localhost:8100/api/v1/agents -H 'X-API-Key: dev-key'
```

Or via Docker (`Dockerfile` included; exposes 8100).

## Registering your agents

Edit [`registry/capabilities.yaml`](registry/capabilities.yaml) — it ships with
three example entries to replace:

```yaml
agents:
  - agent_id: my-reviewer
    description: Reviews a diff and reports defects.
    externally_callable: true
    trust_level: standard        # standard | elevated
    allowed_tools: [Read, Grep]
    max_tokens: 16384
```

Then tell the gateway how to run one. `A2A_INVOKER_TEMPLATE` is a command line
with `{agent_id}`, `{prompt}`, and `{context}` placeholders:

```bash
A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} --prompt {prompt}'
```

The template is split into arguments *before* placeholders are substituted and
is executed without a shell, so a prompt can never inject extra arguments. Omit
`{prompt}` and it is written to the command's stdin instead.

[`examples/`](examples/) has worked configurations, including a 15-agent
registry for the Claude Code conductor plugin suite and instructions for
registering a custom executor in Python.

## Configuration

Env-driven — see [`.env.example`](.env.example):

| Var | Default | Purpose |
|-----|---------|---------|
| `API_KEYS` | — | Comma-separated keys callers must present. **Required.** |
| `PORT` | `8100` | Listen port |
| `RATE_LIMIT_RPM` | `60` | Per-caller requests/minute |
| `A2A_REGISTRY_PATH` | `registry/capabilities.yaml` | Which registry to load |
| `A2A_INVOKER_EXECUTOR` | `subprocess` | `subprocess` or `echo` |
| `A2A_INVOKER_TEMPLATE` | — | Command that runs an agent. Required for `subprocess`. |
| `A2A_INVOKER_TIMEOUT_S` | `300` | Seconds before an invocation is killed |
| `A2A_AUDIT_EVENT_ROUTER_URL` | `http://localhost:8085/events` | Where audit events are POSTed |
| `A2A_AUDIT_TIMEOUT_S` | `1.5` | Audit sink timeout |

Audit emission is best-effort: an unreachable sink logs a warning and never
blocks an invocation. Any endpoint accepting a JSON body works —
[`bulletproof-event-router`](https://github.com/bulletproofsoftware-ai/bulletproof-event-router)
is one such sink.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite covers authentication, trust levels, rate limiting, registry loading,
the invoker's template rendering and executors, and the MCP bridge. It needs no
agent runtime and no network.

## Security

See [SECURITY.md](SECURITY.md) for the threat model, the trust-level design, and
how to report a vulnerability.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
