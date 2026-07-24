# Software Bill of Materials — bulletproof-a2a-gateway

A machine-readable CycloneDX 1.6 SBOM is committed alongside this document:
[`a2a-gateway.cyclonedx.json`](a2a-gateway.cyclonedx.json).

- **Format:** CycloneDX 1.6 (JSON)
- **Components:** 30 (the full resolved runtime dependency closure of `requirements.txt`)
- **Generated from:** a clean virtualenv install of the six direct dependencies in
  [`requirements.txt`](../requirements.txt), then serialized with `cyclonedx-py`.

> **Reproducibility note.** `requirements.txt` is **unpinned** (no `==` versions). The versions
> below reflect the resolution captured when this SBOM was generated. For reproducible builds
> and deterministic supply-chain provenance, pin these versions (a `requirements.lock` /
> `pip-compile` output is recommended). The scanner's `syft` "unknown-license" low findings are
> a direct consequence of the unpinned manifest — see [scan/scan-report.md](scan/scan-report.md).

## Direct dependencies

From [`requirements.txt`](../requirements.txt):

| Package | Resolved version | License | Purpose |
|---------|------------------|---------|---------|
| `fastapi` | 0.139.2 | MIT | Web framework — routing, request/response models, dependency injection. |
| `uvicorn[standard]` | 0.51.0 | BSD-3-Clause | ASGI server that runs the app. `[standard]` adds `uvloop`, `httptools`, `websockets`, `watchfiles`. |
| `pydantic` | 2.13.4 | MIT | Request/response validation models (`InvokeRequest`, job records, etc.). |
| `httpx` | 0.28.1 | BSD-3-Clause | Async HTTP client used to POST audit events to the event-router. |
| `python-jose[cryptography]` | 3.5.0 | MIT | JOSE/JWT primitives (declared dependency). |
| `pyyaml` | 6.0.3 | MIT | Parses `registry/capabilities.yaml` into the agent registry. |

## License distribution (full 30-component closure)

Permissive licenses throughout — no copyleft/GPL in the runtime closure.

| License | Components |
|---------|-----------:|
| MIT / MIT License | 14 |
| BSD-3-Clause / BSD | 10 |
| Apache-2.0 OR BSD-3-Clause | 1 |
| MPL-2.0 (`certifi`) | 1 |
| MIT-0 | 1 |
| BSD-2-Clause | 1 |
| Apache Software License | 1 |
| PSF-2.0 | 1 |

MPL-2.0 (`certifi`) is a file-level weak copyleft that does not affect the gateway's Apache-2.0
licensing when used as an unmodified library dependency.

## Transitive dependencies

The 24 transitive components (pulled in by the six direct deps and the `uvicorn[standard]` /
`python-jose[cryptography]` extras) include: `starlette`, `anyio`, `sniffio`, `idna`,
`typing_extensions`, `annotated-types`, `pydantic_core`, `httpcore`, `h11`, `certifi`,
`cryptography`, `cffi`, `pycparser`, `ecdsa`, `rsa`, `pyasn1`, `six`, `click`, `uvloop`,
`httptools`, `websockets`, `watchfiles`, `python-dotenv`, `typing-inspection`. See the
CycloneDX JSON for exact versions, PURLs, and hashes.

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
