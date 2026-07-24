# Install & Run — bulletproof-a2a-gateway

## Prerequisites

- **Python 3.11+** (the Docker image pins `python:3.11-slim`; CI tests on 3.12).
- **The `claude` CLI** (Claude Code) installed and on `PATH` at runtime. The gateway invokes
  agents with `claude -p "<prompt>" --agent conductor:<name>`. Without it, every invocation
  returns `claude CLI not found`. See [`src/invoker.py`](../src/invoker.py).
- **The `conductor` agents** available to your `claude` install (the `conductor:*` agent
  namespace the invoker targets).
- (Optional) **An event-router** to receive audit events — see [ADMINISTRATOR.md](ADMINISTRATOR.md).

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

> **Port note.** `.env.example` and the README use **8100**. The `Dockerfile`, the
> `HEALTHCHECK`, and `registry/capabilities.yaml` (`gateway_port`) use **8420**. Pick a port
> explicitly and pass it to `uvicorn --port`. Examples in these docs use **8100** for local
> runs to match `.env.example`.

### Dependencies

`requirements.txt` (unpinned — pins recommended for reproducible installs, see [SBOM.md](SBOM.md)):

```
fastapi
uvicorn[standard]
pydantic
httpx
python-jose[cryptography]
pyyaml
```

## 2. Docker

The included [`Dockerfile`](../Dockerfile) builds on `python:3.11-slim`, runs as a **non-root
user** (`appuser`, uid 10001), exposes **8420**, and has a `curl`-based healthcheck.

```bash
docker build -t a2a-gateway .

docker run --rm -p 8420:8420 \
  -e API_KEYS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  a2a-gateway
```

> **Runtime caveat.** The image does **not** contain the `claude` CLI or the conductor agents.
> Discovery (`/health`, `/api/v1/agents`, `/.well-known/agent.json`, MCP `tools/list`) works
> out of the box, but **actual agent invocation** requires the `claude` CLI to be reachable
> from inside the container (e.g. mounted in, or run the gateway on a host that has it). This
> is by design — the gateway is a front door, not a bundle of the agents.

Verify the container runs as non-root:

```bash
docker run --rm --entrypoint sh a2a-gateway -c 'id -un'   # -> appuser
```

## 3. Smoke test

With the server running (local example uses port 8100; add your key):

```bash
# Health — no auth
curl -s http://localhost:8100/health

# Public A2A agent card — no auth
curl -s http://localhost:8100/.well-known/agent.json

# Discover agents — requires X-API-Key
curl -s http://localhost:8100/api/v1/agents -H "X-API-Key: <your-key>"
```

You should see `agent_count: 15` in `/health` and 15 entries from `/api/v1/agents`.

See [HOW-TO-USE.md](HOW-TO-USE.md) for invocation, polling, and the MCP bridge.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
