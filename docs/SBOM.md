# Software Bill of Materials — bulletproof-a2a-gateway

A machine-readable CycloneDX 1.6 SBOM is committed alongside this document:
[`a2a-gateway.cyclonedx.json`](a2a-gateway.cyclonedx.json).

- **Format:** CycloneDX 1.6 (JSON)
- **Generated from:** a clean virtualenv install of the direct dependencies in
  [`requirements.txt`](../requirements.txt), then serialized with `cyclonedx-py`.

> **The committed JSON predates the removal of `python-jose[cryptography]`** and therefore still
> lists it and its crypto sub-tree (`cryptography`, `cffi`, `pycparser`, `ecdsa`, `rsa`,
> `pyasn1`, `six`). The tables below reflect the **current** manifest. Regenerate the JSON with
> `cyclonedx-py requirements requirements.txt` to bring it back in sync.

> **Reproducibility note.** `requirements.txt` uses compatible-release ranges rather than exact
> pins, so the resolved versions below are a point-in-time snapshot. For reproducible builds,
> generate a lock file (`pip-compile`) and build from that.

## Direct dependencies

From [`requirements.txt`](../requirements.txt) — five packages:

| Package | Resolved version | License | Purpose |
|---------|------------------|---------|---------|
| `fastapi` | 0.140.0 | MIT | Web framework — routing, request/response models, dependency injection. |
| `uvicorn[standard]` | 0.51.0 | BSD-3-Clause | ASGI server that runs the app. `[standard]` adds `uvloop`, `httptools`, `websockets`, `watchfiles`. |
| `pydantic` | 2.13.4 | MIT | Request/response validation models (`InvokeRequest`, job records, etc.). |
| `httpx` | 0.28.1 | BSD-3-Clause | Async HTTP client used to POST audit events to the audit sink. |
| `pyyaml` | 6.0.3 | MIT | Parses `registry/capabilities.yaml` into the agent registry. |

`python-jose[cryptography]` was previously declared but never imported by any module. It was
removed, eliminating the entire `cryptography`/`cffi`/`ecdsa`/`rsa`/`pyasn1` sub-tree from the
runtime closure.

Test-only dependencies live in [`requirements-dev.txt`](../requirements-dev.txt) (`pytest`) and
are not part of the runtime closure.

## Full runtime closure (22 components)

Permissive licenses throughout — no copyleft/GPL.

| License | Components |
|---------|-----------:|
| MIT | 12 |
| BSD-3-Clause / BSD | 7 |
| Apache Software License OR MIT (`uvloop`) | 1 |
| MPL-2.0 (`certifi`) | 1 |
| PSF-2.0 (`typing_extensions`) | 1 |

MPL-2.0 (`certifi`) is a file-level weak copyleft that does not affect the gateway's Apache-2.0
licensing when used as an unmodified library dependency.

## Transitive dependencies

The 17 transitive components pulled in by the five direct deps and the `uvicorn[standard]`
extra: `starlette`, `anyio`, `idna`, `typing_extensions`, `typing-inspection`,
`annotated-types`, `annotated-doc`, `pydantic_core`, `httpcore`, `h11`, `certifi`, `click`,
`uvloop`, `httptools`, `websockets`, `watchfiles`, `python-dotenv`.

## Base image

- **Runtime image:** `python:3.11-slim` (Debian slim). The Dockerfile adds `curl` (for the
  healthcheck) and creates a non-root `appuser` (uid 10001). Rebuild regularly to pick up
  Debian and Python security updates.

## Supply-chain scanning

Dependency and container-manifest scanning is performed by Code Hardener (`trivy`, `grype`,
`syft`). The latest run reports **0 critical / 0 high**. Full results:
[scan/scan-report.md](scan/scan-report.md). Machine-readable SARIF:
[scan/scan-report.sarif.json](scan/scan-report.sarif.json).

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE).
