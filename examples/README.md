# Examples

The gateway is agent-runtime agnostic. Two things decide what it can invoke:

1. **The registry** — which agent ids exist and what trust each one needs.
2. **The invoker template** — the command that actually runs an agent.

This directory holds worked examples of both.

| File | What it is |
|------|------------|
| [`capabilities.conductor.yaml`](capabilities.conductor.yaml) | A 15-agent registry for the Claude Code conductor plugin suite. Optional. |

## Registering your own agents

Edit [`../registry/capabilities.yaml`](../registry/capabilities.yaml), or point
`A2A_REGISTRY_PATH` at a file of your own:

```yaml
version: "1.0.0"
gateway_port: 8100

agents:
  - agent_id: my-reviewer
    description: Reviews a diff and reports defects.
    externally_callable: true
    trust_level: standard          # standard | elevated
    allowed_tools: [Read, Grep]    # advisory — published in discovery
    max_tokens: 16384
```

The registry is loaded once at startup. Restart the gateway after editing it.

Agents with `trust_level: elevated` additionally require callers to send
`X-Trust-Level: elevated`. Put anything that writes behind elevated trust.
Setting `externally_callable: false` keeps an entry in the file but hides it
from every external surface.

## Wiring the invoker

`A2A_INVOKER_TEMPLATE` is a command line with placeholders. It is split with
`shlex` **before** substitution and executed directly — never through a shell —
so a prompt containing spaces, quotes, or shell metacharacters stays a single
argument and cannot inject extra ones.

| Placeholder | Value |
|-------------|-------|
| `{agent_id}` | The agent id from the registry |
| `{prompt}` | The full prompt (context prepended when supplied) |
| `{context}` | The context alone; empty string when not supplied |

### A CLI that takes flags

```bash
A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} --prompt {prompt}'
```

If the prompt is **positional** rather than behind a flag, end your options with
`--` so a prompt starting with a dash is treated as data, not as an option of
the program you are invoking:

```bash
A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id} -- {prompt}'
```

### A CLI that reads stdin

Omit `{prompt}` and the prompt is written to the process's stdin:

```bash
A2A_INVOKER_TEMPLATE='my-agent-cli --name {agent_id}'
```

### An HTTP shim

```bash
A2A_INVOKER_TEMPLATE='curl -sf -X POST http://localhost:9000/run/{agent_id} --data-binary @-'
```

### Claude Code conductor agents

```bash
export A2A_REGISTRY_PATH="$PWD/examples/capabilities.conductor.yaml"
export A2A_INVOKER_TEMPLATE='claude -p {prompt} --agent conductor:{agent_id}'
```

This example needs the `claude` CLI on `PATH` with those agents installed. That
is a property of *this example*, not of the gateway.

### Smoke-testing with no runtime at all

The `echo` executor returns the rendered prompt without executing anything, so
you can exercise auth, rate limiting, discovery, and the MCP bridge before you
have an agent runtime:

```bash
A2A_INVOKER_EXECUTOR=echo uvicorn src.main:app --port 8100
```

## Adding a custom executor

If a subprocess is the wrong shape entirely, register a coroutine in
`src/invoker.py`:

```python
async def _invoke_my_runtime(agent_id, full_prompt, context):
    ...
    return InvocationResult(success=True, output=text, return_code=0)

EXECUTORS["my-runtime"] = _invoke_my_runtime
```

Then run with `A2A_INVOKER_EXECUTOR=my-runtime`.

## Audit sink

The gateway POSTs one JSON event per invocation to
`A2A_AUDIT_EVENT_ROUTER_URL`. Any HTTP endpoint that accepts a JSON body works;
[`bulletproof-event-router`](https://github.com/bulletproofsoftware-ai/bulletproof-event-router)
is one such sink. Emission is best-effort — if the sink is unreachable the
invocation still proceeds and a warning is logged.
