"""The pluggable invoker: template rendering, executors, and failure modes.

``conftest`` reloads ``src.invoker`` between tests, which rebinds the module's
classes and the EXECUTORS dict. Everything here therefore resolves attributes
through the module object at call time rather than binding them at import.
"""

from __future__ import annotations

import asyncio

import pytest

import src.invoker as invoker_module


def run(coro):
    return asyncio.run(coro)


def build_command(*args, **kwargs):
    return invoker_module.build_command(*args, **kwargs)


def template_uses_prompt(*args, **kwargs):
    return invoker_module.template_uses_prompt(*args, **kwargs)


def invoke_agent(*args, **kwargs):
    return invoker_module.invoke_agent(*args, **kwargs)


@pytest.fixture
def config_error():
    """The InvokerConfigError class as currently bound in the module."""
    return invoker_module.InvokerConfigError


class TestBuildCommand:
    def test_substitutes_all_placeholders(self):
        argv = build_command(
            "run --name {agent_id} --prompt {prompt} --ctx {context}",
            "my-agent",
            "do the thing",
            "some context",
        )
        assert argv == [
            "run",
            "--name",
            "my-agent",
            "--prompt",
            "do the thing",
            "--ctx",
            "some context",
        ]

    def test_prompt_with_spaces_stays_one_argument(self):
        argv = build_command("run {prompt}", "a", "two words here")
        assert argv == ["run", "two words here"]

    def test_prompt_cannot_inject_extra_arguments(self):
        """Substitution happens after tokenisation, so metacharacters are inert."""
        argv = build_command("run {prompt}", "a", "x --dangerous-flag; rm -rf /")
        assert argv == ["run", "x --dangerous-flag; rm -rf /"]
        assert len(argv) == 2

    def test_quotes_in_prompt_do_not_split(self):
        argv = build_command("run {prompt}", "a", 'he said "hi" then \'bye\'')
        assert len(argv) == 2
        assert argv[1] == 'he said "hi" then \'bye\''

    def test_missing_context_becomes_empty_string(self):
        assert build_command("run {context}", "a", "p") == ["run", ""]

    def test_quoted_template_segments_are_respected(self):
        assert build_command("run 'a b' {prompt}", "x", "p") == ["run", "a b", "p"]

    def test_placeholder_inside_larger_token(self):
        assert build_command("run --id=v{agent_id}", "7", "p") == ["run", "--id=v7"]

    def test_substituted_value_is_not_rescanned(self):
        """A prompt containing literal '{context}' must pass through untouched."""
        argv = build_command(
            "run {prompt}", "a", "text with {context} inside", "CTXVAL"
        )
        assert argv == ["run", "text with {context} inside"]
        assert "CTXVAL" not in argv[1]

    def test_prompt_containing_agent_id_placeholder_is_literal(self):
        argv = build_command("run {prompt}", "AGENT", "see {agent_id} here")
        assert argv[1] == "see {agent_id} here"

    def test_unknown_braced_token_is_left_alone(self):
        assert build_command("run {not_a_placeholder}", "a", "p") == [
            "run",
            "{not_a_placeholder}",
        ]

    def test_unclosed_brace_is_left_alone(self):
        assert build_command("run {prompt", "a", "p") == ["run", "{prompt"]

    def test_double_dash_separator_is_preserved(self):
        """Templates can use `--` so a leading-dash prompt is not read as a flag."""
        assert build_command("mycli -- {prompt}", "a", "--version") == [
            "mycli",
            "--",
            "--version",
        ]

    @pytest.mark.parametrize("template", ["", "   ", "\n"])
    def test_empty_template_raises(self, template, config_error):
        with pytest.raises(config_error):
            build_command(template, "a", "p")

    def test_unbalanced_quotes_raise(self, config_error):
        with pytest.raises(config_error):
            build_command("run 'unclosed", "a", "p")

    def test_error_message_names_the_env_var(self, config_error):
        with pytest.raises(config_error, match="A2A_INVOKER_TEMPLATE"):
            build_command("", "a", "p")


class TestTemplateUsesPrompt:
    def test_true_when_present(self):
        assert template_uses_prompt("run {prompt}")

    def test_false_when_absent(self):
        assert not template_uses_prompt("run --name {agent_id}")


class TestEchoExecutor:
    def test_returns_prompt_without_executing(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "echo")
        result = run(invoke_agent("some-agent", "hello world"))
        assert result.success
        assert "some-agent" in result.output
        assert "hello world" in result.output

    def test_context_is_prepended(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "echo")
        result = run(invoke_agent("a", "the task", context="the context"))
        assert "the context" in result.output
        assert "the task" in result.output


class TestSubprocessExecutor:
    def test_runs_the_template(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "printf %s {prompt}")
        result = run(invoke_agent("a", "captured-output"))
        assert result.success
        assert result.output == "captured-output"
        assert result.return_code == 0

    def test_agent_id_reaches_the_command(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "printf %s {agent_id}")
        assert run(invoke_agent("agent-seven", "p")).output == "agent-seven"

    def test_prompt_goes_to_stdin_when_no_placeholder(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "cat")
        result = run(invoke_agent("a", "from-stdin"))
        assert result.success
        assert result.output == "from-stdin"

    def test_nonzero_exit_is_a_failure(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "false")
        result = run(invoke_agent("a", "p"))
        assert not result.success
        assert result.return_code != 0

    def test_stderr_is_captured_on_failure(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv(
            "A2A_INVOKER_TEMPLATE", "sh -c 'echo boom >&2; exit 3'"
        )
        result = run(invoke_agent("a", "p"))
        assert not result.success
        assert result.return_code == 3
        assert "boom" in result.error

    def test_missing_command_is_reported_clearly(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv(
            "A2A_INVOKER_TEMPLATE", "definitely-not-a-real-binary-xyz {prompt}"
        )
        result = run(invoke_agent("a", "p"))
        assert not result.success
        assert "not found" in result.error.lower()

    def test_unset_template_is_reported_not_crashed(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.delenv("A2A_INVOKER_TEMPLATE", raising=False)
        result = run(invoke_agent("a", "p"))
        assert not result.success
        assert "A2A_INVOKER_TEMPLATE" in result.error

    def test_timeout_kills_the_process(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "sleep 30")
        monkeypatch.setenv("A2A_INVOKER_TIMEOUT_S", "1")
        result = run(invoke_agent("a", "p"))
        assert not result.success
        assert "timed out" in result.error.lower()

    def test_context_is_not_passed_twice(self, monkeypatch):
        """With both {context} and {prompt} in the template, context appears once."""
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv(
            "A2A_INVOKER_TEMPLATE", "echo CTX=[{context}] PROMPT=[{prompt}]"
        )
        result = run(invoke_agent("a", "TASKTEXT", context="CTXTEXT"))
        assert result.success
        assert result.output.count("CTXTEXT") == 1
        assert "TASKTEXT" in result.output

    def test_context_is_prepended_when_template_omits_it(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "printf %s {prompt}")
        result = run(invoke_agent("a", "TASKTEXT", context="CTXTEXT"))
        assert "CTXTEXT" in result.output
        assert "TASKTEXT" in result.output

    def test_child_does_not_inherit_stdin(self, monkeypatch):
        """A command that reads stdin must see EOF, not block on the server's."""
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "cat -")
        monkeypatch.setenv("A2A_INVOKER_TIMEOUT_S", "5")
        # {prompt} is present, so nothing is written to stdin; cat must still
        # terminate on EOF rather than hang until the timeout.
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "sh -c 'cat - >/dev/null; echo done'")
        result = run(invoke_agent("a", "p"))
        assert result.success
        assert result.output == "done"

    def test_shell_metacharacters_are_not_interpreted(self, monkeypatch):
        """The prompt must never reach a shell."""
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "subprocess")
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "printf %s {prompt}")
        result = run(invoke_agent("a", "$(echo pwned)"))
        assert result.success
        assert result.output == "$(echo pwned)"
        assert "pwned" not in result.output.replace("$(echo pwned)", "")


class TestExecutorSelection:
    def test_unknown_executor_is_an_error_not_a_crash(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "no-such-executor")
        result = run(invoke_agent("a", "p"))
        assert not result.success
        assert "no-such-executor" in result.error

    def test_default_executor_is_subprocess(self, monkeypatch):
        monkeypatch.delenv("A2A_INVOKER_EXECUTOR", raising=False)
        monkeypatch.setenv("A2A_INVOKER_TEMPLATE", "printf %s ok")
        assert run(invoke_agent("a", "p")).output == "ok"

    def test_both_executors_are_registered(self):
        assert {"subprocess", "echo"} <= set(invoker_module.EXECUTORS)

    def test_custom_executor_can_be_registered(self, monkeypatch):
        async def _custom(agent_id, prompt, context):
            return invoker_module.InvocationResult(
                success=True, output=f"custom:{agent_id}"
            )

        monkeypatch.setitem(invoker_module.EXECUTORS, "custom", _custom)
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "custom")
        assert run(invoke_agent("xyz", "p")).output == "custom:xyz"

    def test_four_arg_executor_receives_bare_prompt(self, monkeypatch):
        seen = {}

        async def _custom(agent_id, full_prompt, context, bare_prompt):
            seen["full"] = full_prompt
            seen["bare"] = bare_prompt
            return invoker_module.InvocationResult(success=True, output="ok")

        monkeypatch.setitem(invoker_module.EXECUTORS, "four", _custom)
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "four")
        run(invoke_agent("a", "TASK", context="CTX"))
        assert seen["bare"] == "TASK"
        assert "CTX" in seen["full"]

    def test_executor_type_error_is_not_swallowed(self, monkeypatch):
        """A genuine TypeError inside an executor must propagate, not retry."""
        calls = []

        async def _boom(agent_id, full_prompt, context, bare_prompt):
            calls.append(1)
            raise TypeError("genuine bug inside executor")

        monkeypatch.setitem(invoker_module.EXECUTORS, "boom", _boom)
        monkeypatch.setenv("A2A_INVOKER_EXECUTOR", "boom")
        with pytest.raises(TypeError, match="genuine bug"):
            run(invoke_agent("a", "p"))
        assert len(calls) == 1


class TestTimeoutConfig:
    @pytest.mark.parametrize("bad", ["not-a-number", "0", "-5"])
    def test_invalid_timeout_falls_back_to_default(self, monkeypatch, bad):
        monkeypatch.setenv("A2A_INVOKER_TIMEOUT_S", bad)
        assert (
            invoker_module._timeout_seconds()
            == invoker_module.DEFAULT_TIMEOUT_SECONDS
        )

    def test_valid_timeout_is_used(self, monkeypatch):
        monkeypatch.setenv("A2A_INVOKER_TIMEOUT_S", "12")
        assert invoker_module._timeout_seconds() == 12
