"""Invokes conductor agents via the Claude Code CLI as async subprocesses."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

INVOKE_TIMEOUT_SECONDS = 300


@dataclass
class InvocationResult:
    """Result of an agent invocation."""

    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    return_code: Optional[int] = None


async def invoke_agent(
    agent_id: str,
    prompt: str,
    context: Optional[str] = None,
) -> InvocationResult:
    """Invoke a conductor agent via claude CLI as an async subprocess.

    Runs: claude -p "prompt" --agent conductor:{agent_id}

    Args:
        agent_id: The conductor agent identifier (e.g. "conductor-architect").
        prompt: The prompt to send to the agent.
        context: Optional additional context to prepend to the prompt.

    Returns:
        InvocationResult with stdout captured as output.
    """
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nTask:\n{prompt}"

    # Strip the "conductor-" prefix if present, since the CLI uses --agent conductor:{name}
    agent_name = agent_id
    if agent_name.startswith("conductor-"):
        agent_name = agent_name[len("conductor-"):]

    cmd = [
        "claude",
        "-p",
        full_prompt,
        "--agent",
        f"conductor:{agent_name}",
    ]

    logger.info("Invoking agent %s with timeout %ds", agent_id, INVOKE_TIMEOUT_SECONDS)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=INVOKE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Agent %s timed out after %ds", agent_id, INVOKE_TIMEOUT_SECONDS)
            return InvocationResult(
                success=False,
                error=f"Agent invocation timed out after {INVOKE_TIMEOUT_SECONDS}s",
                return_code=-1,
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""

        if proc.returncode == 0:
            logger.info("Agent %s completed successfully", agent_id)
            return InvocationResult(
                success=True,
                output=stdout_text,
                return_code=0,
            )
        else:
            logger.error("Agent %s failed (rc=%d): %s", agent_id, proc.returncode, stderr_text)
            return InvocationResult(
                success=False,
                output=stdout_text if stdout_text else None,
                error=stderr_text or f"Process exited with code {proc.returncode}",
                return_code=proc.returncode,
            )

    except FileNotFoundError:
        logger.error("claude CLI not found in PATH")
        return InvocationResult(
            success=False,
            error="claude CLI not found. Ensure Claude Code is installed and in PATH.",
            return_code=-1,
        )
    except Exception as exc:
        logger.error("Unexpected error invoking agent %s: %s", agent_id, exc)
        return InvocationResult(
            success=False,
            error=str(exc),
            return_code=-1,
        )
