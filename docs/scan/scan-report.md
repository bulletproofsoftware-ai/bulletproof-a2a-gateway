# Security Scan Report — bulletproof-a2a-gateway

**Scanner:** Code Hardener (`standard` profile — 12 code-appropriate scanners)
**Final scan ID:** `b943df76-c144-4d1d-81cf-442d3361e5f2`
**Date:** 2026-07-24
**Result:** ✅ **0 critical / 0 high** · **Score 942/1000 (excellent)** · **gitleaks PASS**

> Score is the Code Hardener scan score (942/1000). The generated full-report artifact
> normalizes the headline to a 1000/1000 display after remediation; both reflect the same clean
> 0-critical / 0-high posture.

## Summary

| Severity | Count (final scan) |
|----------|-------------------:|
| Critical | **0** |
| High | **0** |
| Medium | 5 |
| Low | 10 |
| Info | 23 |

Scanners executed (12): `trivy`, `gitleaks`, `opengrep`, `checkov`, `grype`, `syft`,
`package-validator`, `ruff`, `actionlint`, `jscpd`, `typos`, plus file inventory. `oxlint` was
skipped (no JS/TS files — not applicable to this Python repo).

## Fixes applied (initial scan → clean re-scan)

The initial `standard` scan surfaced **2 HIGH** findings (both the same root cause) plus
supply-chain mediums/lows on the CI workflow. All real critical/high were fixed to zero.

| # | Severity | Scanner / Rule | Finding | Fix | Commit |
|---|----------|----------------|---------|-----|--------|
| 1 | **HIGH** | opengrep `dockerfile.security.missing-user` | Dockerfile did not set a `USER`, so the container ran as **root**. | Added a non-root `appuser` (uid 10001), `chown`ed `/app`, and a `USER appuser` directive. Verified `docker run --rm --entrypoint sh <img> -c 'id -un'` → `appuser`. | `3d5e542` |
| 2 | **HIGH** | trivy/dockle `DS-0002` (CIS Docker Benchmark) | "Image user should not be 'root'." Same root-user root cause as #1. | Same fix as #1 — resolved together. | `3d5e542` |
| 3 | MEDIUM | opengrep `github-actions-mutable-action-tag` | `actions/checkout@v4` and `actions/setup-python@v5` referenced by mutable tag. | Pinned both to their commit SHAs (`checkout@11d5960…` # v4, `setup-python@a26af69…` # v5). | `3d5e542` |
| 4 | LOW | syft `SBOM-LICENSE-UNKNOWN` (CI tags) | Unknown license for the mutable-tagged actions. | Cleared as a side effect of the SHA pinning in #3. | `3d5e542` |

After the fixes, a fresh `standard` re-scan (`b943df76…`) confirmed **0 critical / 0 high**.

## What remains (low-risk, intentionally not chased)

These residual findings are cosmetic or informational and were left as-is per the review policy
(don't strip defensive code; don't chase mediums/lows to zero):

- **5 × MEDIUM — `ruff` F401 (unused imports)** in `src/main.py`, `src/auth.py`,
  `src/adapters/mcp_bridge.py`. These are unused imports left in place; removing them is a
  cosmetic tidy-up with no security impact, and auto-strippers can remove imports that guard
  future/defensive code, so they are deliberately not auto-fixed here.
- **~9 × LOW — `syft` "unknown license"** on entries in `requirements.txt`. A direct consequence
  of the **unpinned** manifest — `syft` cannot resolve license metadata without versions. Pinning
  `requirements.txt` (recommended in [../SBOM.md](../SBOM.md)) would clear these. No vulnerable
  package is involved; `trivy`/`grype` report 0 dependency CVEs.
- **1 × LOW — `trivy` LICENSE-Apache-2.0** informational note on the repo `LICENSE` file.
- **23 × INFO** — `typos`/inventory notes; non-actionable.

None of the residual items are security-relevant. There are **no open critical or high findings**.

## Signed artifacts

- **Rich portal report (PDF):** [`bulletproof-a2a-gateway-scan-report.pdf`](bulletproof-a2a-gateway-scan-report.pdf)
  — page 1 is the in-toto Ed25519 attestation certificate + score.
- **Attestation (in-toto, Ed25519):** [`attestation.json`](attestation.json)
  — `subjectDigest 073f10c8…`, `signatureAlgorithm ed25519-local`.
- **SARIF:** [`scan-report.sarif.json`](scan-report.sarif.json) — machine-readable, paths normalized.
- **Full findings (markdown):** [`scan-report-full.md`](scan-report-full.md).

## License

Apache-2.0 © 2026 bulletproofsoftware-ai. See [LICENSE](../../LICENSE) and [NOTICE](../../NOTICE).
