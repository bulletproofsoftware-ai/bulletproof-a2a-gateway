# bulletproof-a2a-gateway

**An agent-to-agent gateway: authenticated, rate-limited, audited invocation between agents.**

![bulletproof-a2a-gateway — overview](docs/media/infographic.png)

> 📚 **Docs:** [`docs/`](docs/) (overview, install, how-to-use, administrator, SBOM, security scan).
> 🎬 **Media:** slide deck, explainer video, and briefing doc in [`media/`](media/).

`bulletproof-a2a-gateway` is a FastAPI service that lets agents (and external callers)
invoke other agents' capabilities safely. It authenticates callers, enforces
per-caller rate limits, audits every invocation, and bridges to MCP so an agent's
capabilities can be exposed and called over a uniform API.

## What it does

- **Capability registry** — agents declare their capabilities in
  [`registry/capabilities.yaml`](registry/capabilities.yaml).
- **Authenticated invocation** — callers present an API key; only registered
  capabilities are callable.
- **Rate limiting** — per-key request limits.
- **Audit** — every invocation is logged.
- **MCP bridge** — exposes/consumes capabilities over the Model Context Protocol.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env       # set API_KEYS (comma-separated)
uvicorn src.main:app --host 0.0.0.0 --port 8100
```

Or via Docker (`Dockerfile` included).

## Configuration

Env-driven — see [`.env.example`](.env.example):

| Var | Purpose |
|-----|---------|
| `API_KEYS` | Comma-separated keys callers must present. **Required.** |
| `PORT` | Listen port (default 8100) |
| `RATE_LIMIT_RPM` | Per-key requests/minute |
| `AUDIT_DB_PATH` | Audit log location |

## Registering capabilities

Edit `registry/capabilities.yaml` to declare which agent capabilities are callable.
Only capabilities marked callable are exposed.

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
