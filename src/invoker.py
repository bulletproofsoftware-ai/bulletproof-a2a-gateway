"""Pluggable agent invocation.

The gateway does not assume any particular agent runtime. An **executor**
turns an ``(agent_id, prompt, context)`` triple into a process invocation.
Two executors ship in the box:

``subprocess`` (default)
    Renders a configurable command template and runs it as an async
    subprocess. The template is supplied via ``A2A_INVOKER_TEMPLATE``.

``echo``
    Returns the rendered prompt without executing anything. Useful for
    smoke-testing the gateway (auth, rate limiting, registry, MCP bridge)
    without provisioning a real agent runtime.

Select the executor with ``A2A_INVOKER_EXECUTOR``.

Command template
----------------
``A2A_INVOKER_TEMPLATE`` is a shell-style command line, parsed with
``shlex.split``, containing zero or more of these placeholders:

    ``{agent_id}``  the agent id as registered in ``capabilities.yaml``
    ``{prompt}``    the full prompt (context prepended when supplied)
    ``{context}``   the context alone, empty string when not supplied

Placeholders are substituted **after** the template is split into argv, so
a value containing spaces or quotes stays a single argument and can never
inject additional arguments. Substitution is single-pass, so a prompt that
itself contains ``{context}`` is passed through literally. The rendered
command is executed directly (``create_subprocess_exec``) — never through a
shell.

If the prompt is passed positionally, end your flags with ``--`` so a prompt
beginning with a dash is not parsed as an option by the target program::

    A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} -- {prompt}'

Example — a CLI that takes the agent name and prompt as flags::

    A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} --prompt {prompt}'

Example — a local HTTP shim::

    A2A_INVOKER_TEMPLATE='curl -sf -X POST http://localhost:9000/run -d {prompt}'

If ``{prompt}`` is absent from the template the prompt is written to the
command's stdin instead, so line-oriented tools work without modification.

See ``examples/`` for ready-made configurations.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import shlex
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 300


class InvokerConfigError(RuntimeError):
    """Raised when the invoker is not configured well enough to run."""


@dataclass
class InvocationResult:
    """Result of an agent invocation."""

    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    return_code: Optional[int] = None


def _timeout_seconds() -> int:
    raw = os.environ.get("A2A_INVOKER_TIMEOUT_S", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        logger.warning(
            "A2A_INVOKER_TIMEOUT_S=%r is not a number; using %ds",
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS
    if value <= 0:
        logger.warning(
            "A2A_INVOKER_TIMEOUT_S=%r must be positive; using %ds",
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS
    return value


def build_command(
    template: str,
    agent_id: str,
    prompt: str,
    context: Optional[str] = None,
) -> list[str]:
    """Render ``template`` into an argv list.

    The template is tokenised first, then each token has its placeholders
    substituted. Substituted values therefore never split into extra argv
    entries regardless of the characters they contain.

    Raises:
        InvokerConfigError: if the template is empty or unparseable.
    """
    if not template or not template.strip():
        raise InvokerConfigError(
            "A2A_INVOKER_TEMPLATE is not set. Set it to the command that runs "
            "your agent, e.g. 'my-agent-cli --name {agent_id} --prompt {prompt}'."
        )

    try:
        tokens = shlex.split(template)
    except ValueError as exc:
        raise InvokerConfigError(
            f"A2A_INVOKER_TEMPLATE is not a valid command line: {exc}"
        ) from exc

    if not tokens:
        raise InvokerConfigError("A2A_INVOKER_TEMPLATE produced an empty command.")

    substitutions = {
        "agent_id": agent_id,
        "prompt": prompt,
        "context": context or "",
    }

    # Single-pass substitution. Scanning each token once means a substituted
    # value is never itself rescanned, so a prompt containing the literal text
    # "{context}" is passed through untouched instead of being expanded.
    argv: list[str] = []
    for token in tokens:
        out: list[str] = []
        i = 0
        while i < len(token):
            if token[i] == "{":
                end = token.find("}", i)
                if end != -1:
                    name = token[i + 1 : end]
                    if name in substitutions:
                        out.append(substitutions[name])
                        i = end + 1
                        continue
            out.append(token[i])
            i += 1
        argv.append("".join(out))
    return argv


def template_uses_prompt(template: str) -> bool:
    """Whether ``template`` places the prompt on the command line."""
    return "{prompt}" in template


async def _invoke_subprocess(
    agent_id: str,
    full_prompt: str,
    context: Optional[str],
    bare_prompt: Optional[str] = None,
) -> InvocationResult:
    template = os.environ.get("A2A_INVOKER_TEMPLATE", "")
    timeout = _timeout_seconds()

    # When the template takes {context} separately, pass the bare prompt so the
    # context is not delivered twice.
    if "{context}" in template and bare_prompt is not None:
        prompt_arg = bare_prompt
    else:
        prompt_arg = full_prompt

    try:
        cmd = build_command(template, agent_id, prompt_arg, context)
    except InvokerConfigError as exc:
        logger.error("invoker misconfigured: %s", exc)
        return InvocationResult(success=False, error=str(exc), return_code=-1)

    # When the template has no {prompt} placeholder, feed the prompt on stdin
    # so line-oriented tools work unmodified.
    stdin_payload: Optional[bytes] = None
    if not template_uses_prompt(template):
        stdin_payload = prompt_arg.encode("utf-8")

    logger.info("Invoking agent %s via %s (timeout %ds)", agent_id, cmd[0], timeout)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            # Never inherit the server's stdin: a child that reads it would
            # block forever waiting on input that will never arrive.
            stdin=(
                asyncio.subprocess.PIPE
                if stdin_payload is not None
                else asyncio.subprocess.DEVNULL
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_payload),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Agent %s timed out after %ds", agent_id, timeout)
            return InvocationResult(
                success=False,
                error=f"Agent invocation timed out after {timeout}s",
                return_code=-1,
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""

        if proc.returncode == 0:
            logger.info("Agent %s completed successfully", agent_id)
            return InvocationResult(success=True, output=stdout_text, return_code=0)

        logger.error(
            "Agent %s failed (rc=%s): %s", agent_id, proc.returncode, stderr_text
        )
        return InvocationResult(
            success=False,
            output=stdout_text or None,
            error=stderr_text or f"Process exited with code {proc.returncode}",
            return_code=proc.returncode,
        )

    except FileNotFoundError:
        logger.error("invoker command not found: %s", cmd[0])
        return InvocationResult(
            success=False,
            error=(
                f"Invoker command '{cmd[0]}' not found in PATH. Check "
                "A2A_INVOKER_TEMPLATE and ensure the executable is installed."
            ),
            return_code=-1,
        )
    except PermissionError:
        logger.error("invoker command not executable: %s", cmd[0])
        return InvocationResult(
            success=False,
            error=f"Invoker command '{cmd[0]}' is not executable.",
            return_code=-1,
        )
    except Exception as exc:  # noqa: BLE001 — surface any runtime failure as a result
        logger.error("Unexpected error invoking agent %s: %s", agent_id, exc)
        return InvocationResult(success=False, error=str(exc), return_code=-1)


async def _invoke_echo(
    agent_id: str,
    full_prompt: str,
    _context: Optional[str],
    _bare_prompt: Optional[str] = None,
) -> InvocationResult:
    """No-op executor that echoes what would have been sent."""
    logger.info("echo executor: agent=%s prompt_len=%d", agent_id, len(full_prompt))
    return InvocationResult(
        success=True,
        output=f"[echo executor] agent={agent_id}\n{full_prompt}",
        return_code=0,
    )


#: Executor name -> coroutine. Extend this map to register your own executor.
EXECUTORS = {
    "subprocess": _invoke_subprocess,
    "echo": _invoke_echo,
}

DEFAULT_EXECUTOR = "subprocess"


def _selected_executor_name() -> str:
    name = os.environ.get("A2A_INVOKER_EXECUTOR", DEFAULT_EXECUTOR).strip()
    return name or DEFAULT_EXECUTOR


def _accepts_bare_prompt(executor) -> bool:
    """Whether ``executor`` takes the optional 4th (bare prompt) argument."""
    try:
        params = inspect.signature(executor).parameters
    except (TypeError, ValueError):  # builtins / C callables
        return False
    if any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params.values()
    ):
        return True
    positional = [
        p
        for p in params.values()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    return len(positional) >= 4


async def invoke_agent(
    agent_id: str,
    prompt: str,
    context: Optional[str] = None,
) -> InvocationResult:
    """Invoke an agent through the configured executor.

    Args:
        agent_id: Agent identifier as registered in ``capabilities.yaml``.
        prompt: The prompt to send to the agent.
        context: Optional additional context prepended to the prompt.

    Returns:
        InvocationResult with the executor's stdout captured as output.
    """
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nTask:\n{prompt}"

    name = _selected_executor_name()
    executor = EXECUTORS.get(name)
    if executor is None:
        known = ", ".join(sorted(EXECUTORS))
        logger.error("unknown executor %r (known: %s)", name, known)
        return InvocationResult(
            success=False,
            error=f"Unknown A2A_INVOKER_EXECUTOR '{name}'. Known executors: {known}.",
            return_code=-1,
        )

    # Executors may accept an optional 4th argument (the prompt without the
    # context prefix). Custom 3-argument executors keep working unchanged.
    # Arity is inspected rather than caught, so a genuine TypeError raised
    # inside an executor still propagates.
    if _accepts_bare_prompt(executor):
        return await executor(agent_id, full_prompt, context, prompt)
    return await executor(agent_id, full_prompt, context)
