"""A2A Agent Interoperability Gateway — FastAPI application.

Exposes the agents declared in the capabilities registry to external callers
over REST, the A2A agent card, and an MCP bridge.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.agents import get_agent, list_agents
from src.adapters.mcp_bridge import router as mcp_router
from src.audit import emit_audit_event
from src.auth import require_api_key
from src.invoker import invoke_agent
from src.rate_limiter import rate_limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SERVICE_VERSION = "1.1.0"


# --- Job storage (in-memory) ---

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    job_id: str
    agent_id: str
    caller_id: str
    status: JobStatus = JobStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""
    completed_at: Optional[str] = None


_jobs: Dict[str, JobRecord] = {}


# --- Request/Response models ---

class InvokeRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=100000, description="The prompt to send to the agent")
    context: Optional[str] = Field(None, max_length=100000, description="Optional additional context")
    caller_id: str = Field(..., min_length=1, max_length=256, description="Identifier for the calling system")


class InvokeResponse(BaseModel):
    job_id: str
    status: str


class JobResponse(BaseModel):
    job_id: str
    agent_id: str
    caller_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    agent_count: int
    timestamp: str


# --- Background task for agent invocation ---

async def _run_agent_job(
    job_id: str,
    agent_id: str,
    prompt: str,
    context: Optional[str],
    caller_id: str,
    trust_level: str,
) -> None:
    """Background task that runs an agent invocation and updates the job record."""
    job = _jobs.get(job_id)
    if not job:
        logger.error("Job %s not found in store", job_id)
        return

    job.status = JobStatus.RUNNING
    result = await invoke_agent(agent_id, prompt, context)

    if result.success:
        job.status = JobStatus.COMPLETED
        job.result = result.output
    else:
        job.status = JobStatus.FAILED
        job.error = result.error
        if result.output:
            job.result = result.output

    job.completed_at = datetime.now(timezone.utc).isoformat()
    logger.info("Job %s finished with status %s", job_id, job.status)

    await emit_audit_event(
        category="agent.dispatch",
        event="invoke_complete" if result.success else "invoke_failed",
        agent_id=agent_id,
        caller_id=caller_id,
        job_id=job_id,
        trust_level=trust_level,
        extra={
            "channel": "rest",
            "success": result.success,
            "return_code": result.return_code,
        },
    )


# --- App lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("A2A Gateway starting — %d agents registered", len(list_agents()))
    yield
    logger.info("A2A Gateway shutting down")


# --- FastAPI application ---

app = FastAPI(
    title="A2A Agent Interoperability Gateway",
    description=(
        "Exposes the agents declared in the capabilities registry to external "
        "callers via REST, the A2A agent card, and an MCP bridge."
    ),
    version=SERVICE_VERSION,
    lifespan=lifespan,
)

# MCP bridge — exposes the agents as MCP tools at /mcp
app.include_router(mcp_router)


# --- Endpoints ---

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint — no authentication required."""
    return HealthResponse(
        status="healthy",
        service="a2a-gateway",
        version=SERVICE_VERSION,
        agent_count=len(list_agents()),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/api/v1/agents", tags=["Agents"])
async def discover_agents(api_key: str = Depends(require_api_key)):
    """Discover all available agents and their capabilities."""
    return {
        "agents": list_agents(),
        "count": len(list_agents()),
    }


@app.post(
    "/api/v1/agents/{agent_id}/invoke",
    response_model=InvokeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Agents"],
)
async def invoke_agent_endpoint(
    agent_id: str,
    request: InvokeRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    api_key: str = Depends(require_api_key),
):
    """Invoke an agent asynchronously.

    Returns a job_id that can be polled for results.
    """
    # Rate limit by caller_id
    rate_limiter.check(request.caller_id)

    # Validate agent exists
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found. Use GET /api/v1/agents to discover available agents.",
        )

    # Trust level check — elevated agents require the X-Trust-Level header.
    # Enforced identically on the MCP path (see adapters/mcp_bridge.py).
    if agent.trust_level == "elevated":
        trust_header = http_request.headers.get("X-Trust-Level", "standard")
        if trust_header != "elevated":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Agent '{agent_id}' requires elevated trust; "
                    f"got '{trust_header}'. Send X-Trust-Level: elevated."
                ),
            )

    # Create job
    job_id = str(uuid.uuid4())
    job = JobRecord(
        job_id=job_id,
        agent_id=agent_id,
        caller_id=request.caller_id,
        status=JobStatus.PENDING,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _jobs[job_id] = job

    # Emit invoke_start audit event (best-effort)
    await emit_audit_event(
        category="agent.dispatch",
        event="invoke_start",
        agent_id=agent_id,
        caller_id=request.caller_id,
        job_id=job_id,
        trust_level=agent.trust_level,
        extra={"channel": "rest", "prompt_len": len(request.prompt)},
    )

    # Dispatch background invocation
    background_tasks.add_task(
        _run_agent_job,
        job_id,
        agent_id,
        request.prompt,
        request.context,
        request.caller_id,
        agent.trust_level,
    )

    logger.info("Job %s created for agent %s by caller %s", job_id, agent_id, request.caller_id)

    return InvokeResponse(job_id=job_id, status=job.status.value)


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobResponse,
    tags=["Jobs"],
)
async def get_job_status(
    job_id: str,
    api_key: str = Depends(require_api_key),
):
    """Poll for the status and result of an agent invocation job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    return JobResponse(
        job_id=job.job_id,
        agent_id=job.agent_id,
        caller_id=job.caller_id,
        status=job.status.value,
        result=job.result,
        error=job.error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


# --- A2A Agent Card Discovery (public, no auth) ---

@app.get("/.well-known/agent.json", tags=["Discovery"])
async def agent_card():
    """A2A Agent Card discovery endpoint.

    Returns the gateway's capability card per the A2A protocol standard.
    No authentication required — this is a public discovery endpoint.
    """
    agents = list_agents()
    rpm = rate_limiter.max_requests
    agent_cards = [
        {
            "id": a["agent_id"],
            "name": a["agent_id"],
            "description": a["description"],
            "capabilities": a["allowed_tools"],
            "endpoint": f"/api/v1/agents/{a['agent_id']}/invoke",
            "trust_level": a["trust_level"],
            "rate_limit": {"requests_per_minute": rpm},
        }
        for a in agents
    ]

    return {
        "name": "A2A Agent Interoperability Gateway",
        "version": SERVICE_VERSION,
        "description": (
            f"A2A Agent Interoperability Gateway exposing {len(agents)} agent(s)"
        ),
        "protocol_version": "0.2.0",
        "capabilities": [
            "task_execution",
            "capability_discovery",
            "async_polling",
        ],
        "authentication": {
            "type": "api_key",
            "header": "X-API-Key",
        },
        "rate_limits": {"requests_per_minute": rpm},
        "agents": agent_cards,
    }
