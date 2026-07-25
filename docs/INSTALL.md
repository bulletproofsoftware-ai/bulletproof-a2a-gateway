# Install & Run — bulletproof-a2a-gateway

## Prerequisites

- **Python 3.11+** (the Docker image pins `python:3.11-slim`; CI tests on 3.12).
- **pip.**
- **An agent runtime — whatever `A2A_INVOKER_TEMPLATE` points at.** The gateway itself has no
  CLI dependency; it renders a command template and runs it as a subprocess. See
  [`src/invoker.py`](../src/invoker.py) and [`examples/README.md`](../examples/README.md) for
  worked configurations, including an optional one for the Claude Code conductor agents.
- (Optional) **An HTTP audit sink** to receive audit events — see [ADMINISTRATOR.md](ADMINISTRATOR.md).

If you don't have an agent runtime wired up yet, use the `echo` executor (below) to verify the
install with zero dependencies.

## 1. Local (uvicorn)

```bash
git clone https://github.com/bulletproofsoftware-ai/bulletproof-a2a-gateway.git
cd bulletproof-a2a-gateway

pip install -r requirements.txt

cp .env.example .env
# Edit .env and set API_KEYS (see "Configuration" below). REQUIRED — the server
# returns HTTP 500 on any authenticated route if no keys are configured.

# Generate a key:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Load the env and start the server. `.env` is not auto-loaded by the app, so export it:

```bash
set -a && . ./.env && set +a
uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8100}"
```

### Dependencies

`requirements.txt` (range-pinned — compatible-release ranges so patch/minor updates flow in
while a major bump stays an explicit decision; see [SBOM.md](SBOM.md)):

```
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
pydantic>=2.7,<3.0
httpx>=0.27,<1.0
pyyaml>=6.0,<7.0
```

## 2. Docker

The included [`Dockerfile`](../Dockerfile) builds on `python:3.11-slim`, runs as a **non-root
user** (`appuser`, uid 10001), exposes **8100**, and has a `curl`-based healthcheck.

```bash
docker build -t a2a-gateway .

docker run --rm -p 8100:8100 \
  -e API_KEYS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e A2A_INVOKER_EXECUTOR=echo \
  a2a-gateway
```

> **Runtime caveat.** The image does **not** contain any agent runtime. Discovery (`/health`,
> `/api/v1/agents`, `/.well-known/agent.json`, MCP `tools/list`) works out of the box with any
> executor. **Actual agent invocation** with the `subprocess` executor requires whatever
> `A2A_INVOKER_TEMPLATE` names to be reachable from inside the container (e.g. mounted in, or
> run the gateway on a host that has it). This is by design — the gateway is a front door, not
> a bundle of the agents. Use `A2A_INVOKER_EXECUTOR=echo` to verify the container works before
> wiring up a real runtime.

Verify the container runs as non-root:

```bash
docker run --rm --entrypoint sh a2a-gateway -c 'id -un'   # -> appuser
```

## 3. Configuration — environment variables

All of these are documented in [`.env.example`](../.env.example):

| Var | Default | Purpose |
|-----|---------|---------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8100` | Listen port |
| `API_KEYS` | — | Comma-separated keys callers must present in `X-API-Key`. **Required.** |
| `RATE_LIMIT_RPM` | `60` | Per-caller requests/minute. In-process, so it applies per worker. |
| `A2A_REGISTRY_PATH` | `registry/capabilities.yaml` | Which capabilities registry to load. |
| `A2A_INVOKER_EXECUTOR` | `subprocess` | `subprocess` (runs a real command) or `echo` (returns the prompt, no execution — for smoke tests). |
| `A2A_INVOKER_TEMPLATE` | — | Command line with `{agent_id}`, `{prompt}`, `{context}` placeholders. Required when `A2A_INVOKER_EXECUTOR=subprocess`. |
| `A2A_INVOKER_TIMEOUT_S` | `300` | Seconds before an invocation is killed. |
| `A2A_AUDIT_EVENT_ROUTER_URL` | `http://localhost:8085/events` | Where audit events are POSTed. Any HTTP endpoint accepting a JSON body works. |
| `A2A_AUDIT_TIMEOUT_S` | `1.5` | Seconds to wait for the audit sink before giving up. |

Audit emission is best-effort: an unreachable sink logs a warning and never blocks an
invocation. [`bulletproof-event-router`](https://github.com/bulletproofsoftware-ai/bulletproof-event-router)
is one optional sink that understands these events — the gateway works with any HTTP endpoint
that accepts a JSON body.

## 4. Smoke test

With the server running (local example uses port 8100; add your key):

```bash
# Health — no auth
curl -s http://localhost:8100/health

# Public A2A agent card — no auth
curl -s http://localhost:8100/.well-known/agent.json

# Discover agents — requires X-API-Key
curl -s http://localhost:8100/api/v1/agents -H "X-API-Key: <your-key>"
```

You should see `agent_count: 3` in `/health` and 3 entries from `/api/v1/agents` — the example
registry shipped in `registry/capabilities.yaml`.

The fastest way to verify a fresh install end to end, with no agent runtime at all, is the
`echo` executor:

```bash
API_KEYS=dev-key A2A_INVOKER_EXECUTOR=echo uvicorn src.main:app --port 8100

curl -s -X POST http://localhost:8100/api/v1/agents/example-reviewer/invoke \
  -H "X-API-Key: dev-key" -H "Content-Type: application/json" \
  -d '{"prompt": "hello", "caller_id": "smoke-test"}'
```

Poll the returned `job_id` (see [HOW-TO-USE.md](HOW-TO-USE.md)) and you should see the `echo`
executor's output — the prompt it was given, unmodified.

See [HOW-TO-USE.md](HOW-TO-USE.md) for invocation, polling, and the MCP bridge.

## 5. Run the tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite (92 tests) covers authentication, trust levels, rate limiting, registry loading, the
invoker's template rendering and executors, and the MCP bridge. It needs no agent runtime and
no network.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
