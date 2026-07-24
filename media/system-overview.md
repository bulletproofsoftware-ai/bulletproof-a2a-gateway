# Briefing Document: Bulletproof-A2A-Gateway

## Executive Summary

The **bulletproof-a2a-gateway** is a specialized FastAPI service designed to facilitate safe, authenticated, and audited interactions between agents and external callers. Acting as a secure "front door," the gateway exposes 15 specific "conductor agents" by bridging REST and Model Context Protocol (MCP) interfaces to a unified core logic. 

The system's primary function is to wrap the local `claude` CLI, executing agent capabilities as asynchronous subprocesses while enforcing security controls such as API key authentication and rate limiting. While the gateway offers a robust security posture—verified by scans showing zero critical or high vulnerabilities—there are several documented discrepancies between the intended configuration and the current implementation that require operational attention, particularly regarding trust enforcement on REST paths and hard-coded limits.

## Core Architecture and Execution Model

The gateway is built on a "two entry surfaces, one core" architecture. Both the REST API and the MCP bridge funnel requests through a standardized pipeline: **Authentication → Rate-limiting → Registry Lookup → Invocation → Audit.**

### Dual Surfaces
*   **REST API (`/api/v1/...`):** Operates asynchronously. It returns a `job_id` (HTTP 202) upon invocation, requiring the caller to poll for results.
*   **MCP Bridge (`/mcp`):** Operates synchronously via JSON-RPC 2.0. It waits for the agent execution to finish and returns the output inline. Each agent is exposed as a single MCP "tool."

### Execution Mechanics
The gateway does not vendor or bundle the agents themselves. Instead, it utilizes an **async subprocess model** (located in `src/invoker.py`):
*   **Command:** It shells out to the local environment using: `claude -p "<prompt>" --agent conductor:<name>`.
*   **Timeout:** Each invocation has a hard-coded **300-second timeout**.
*   **Requirements:** The `claude` CLI must be installed and available on the system `PATH` at runtime. The Docker image provided does not include the CLI or the agents.

## Agent Registry and Trust Levels

The system manages a fixed set of **15 conductor agents** defined in `registry/capabilities.yaml`. This YAML file serves as the absolute source of truth for agent availability.

### The Agent Roster
All 15 agents are currently marked as `externally_callable`. They are divided into two trust tiers:

| Trust Level | Description | Agents |
| :--- | :--- | :--- |
| **Standard** | Invocable with a valid `X-API-Key`. | conductor-qa, conductor-code-reviewer, conductor-doc-gen, conductor-bug-find, conductor-research, conductor-api-design, conductor-api-docs, conductor-performance, conductor-observability |
| **Elevated** | Requires `X-API-Key` **plus** `X-Trust-Level: elevated`. | conductor-architect, conductor-builder, conductor-refactor, conductor-database, conductor-devops, conductor-compliance |

### Registry Metadata
Each agent entry supports specific configuration keys:
*   **`description`**: Surfaced in discovery and MCP tool lists.
*   **`allowed_tools`**: A subset of local tools the agent may use in gateway mode.
*   **`max_tokens`**: A token budget (default: 16,384) surfaced in annotations.

## Configuration and Operational Reference

The gateway is environment-driven, though it does not auto-load `.env` files; variables must be exported into the process environment.

### Primary Environment Variables
| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `API_KEYS` | (Required) | Comma-separated list of valid keys for `X-API-Key` headers. |
| `HOST` | `0.0.0.0` | Bind address for the server. |
| `PORT` | 8100 / 8420 | Listen port (see Known Gaps regarding mismatch). |
| `RATE_LIMIT_RPM` | 60 | Intended per-key rate limit (currently inert). |
| `A2A_AUDIT_EVENT_ROUTER_URL` | `http://host.docker.internal:8085/events` | Destination for POSTing audit events. |
| `A2A_AUDIT_TIMEOUT_S` | 1.5 | Timeout for audit HTTP requests; failures do not block invokes. |

### Audit and Observability
The gateway employs a "best-effort" audit model. Events (start, complete, failed, error) are sent to an external event-router. If the router is unavailable, errors are logged at the `WARNING` level, but the agent invocation is allowed to proceed to ensure system availability.

## Security Posture

The gateway maintains a high security standard, evidenced by a **Code Hardener score of 942/1000** and a clean **gitleaks** pass.

*   **Non-Root Execution:** The Docker container runs as `appuser` (UID 10001) rather than root.
*   **Supply Chain Security:** GitHub Actions utilize pinned commit SHAs rather than mutable tags for dependencies like `actions/checkout`.
*   **Transport Security:** The gateway speaks plain HTTP. Documentation explicitly states that users must "bring your own transport security" by terminating TLS at a reverse proxy or ingress.
*   **Vulnerability Status:** Latest scans report **0 critical and 0 high vulnerabilities**.

## Documented Configuration vs. Implementation Gaps

There are several known discrepancies between the documentation/configuration and the actual code implementation.

1.  **Trust Enforcement Gap:** The **MCP bridge** correctly enforces the `X-Trust-Level: elevated` requirement. However, the **REST path** currently contains a stub (`pass`) for this check, meaning a standard API key can invoke elevated agents over REST.
2.  **Port Inconsistency:** The `.env.example` and README suggest port **8100**, whereas the Dockerfile and agent registry use port **8420**.
3.  **Inert Variables:** 
    *   `RATE_LIMIT_RPM` is not read by the code; the limiter is hard-coded to 60 requests/60 seconds in `src/rate_limiter.py`.
    *   `AUDIT_DB_PATH` is vestigial; the gateway only supports HTTP-based auditing to an external router and does not write a local database.
4.  **In-Memory Volatility:** Both the rate limiter state and the job store are in-memory. Consequently, limits and active jobs are lost on restart and are not shared across multiple replicas.
5.  **Version Mismatch:** The `/health` endpoint is hard-coded to report version `1.0.0`, while the FastAPI application metadata declares `1.1.0`.

## Important Quotes

> "The gateway is a front door, not a bundle of the agents." 
> — *Context: Regarding the requirement for the claude CLI to be installed on the host or mounted into the container.*

> "Audit failures are logged but never block or fail an invocation." 
> — *Context: Explaining the "best-effort" nature of the audit system to prioritize availability.*

> "If you rely on the trust gate, restrict access at the network layer for the REST endpoint until this is closed." 
> — *Context: Warning administrators about the failure to enforce elevated trust levels on the REST API path.*

## Actionable Insights

*   **Network-Level Trust Gating:** Because the REST API does not currently enforce elevated trust levels, network security policies should be used to restrict access to the `/api/v1/agents/{agent_id}/invoke` endpoint for sensitive agents until a patch is applied.
*   **Load Balancing Considerations:** Since rate limiting is per-replica and in-memory, the effective global rate limit will scale with the number of instances (e.g., 3 replicas allow 180 RPM total). Organizations requiring a strict 60 RPM limit must account for this behavior.
*   **Deployment Port Selection:** Operators should explicitly define the port in the `uvicorn` launch command to avoid confusion between the 8100 (README) and 8420 (Docker) defaults.
*   **CLI Dependency Management:** Ensure the `claude` CLI and the `conductor:*` agent namespace are provisioned in the runtime environment, as discovery endpoints will function without them, but all actual invocations will fail.