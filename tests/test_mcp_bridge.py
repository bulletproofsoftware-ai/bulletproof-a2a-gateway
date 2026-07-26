"""MCP JSON-RPC bridge."""

from __future__ import annotations

from tests.conftest import API_KEY, ELEVATED_KEY

AUTH = {"X-API-Key": API_KEY}


def rpc(client, method, params=None, req_id=1, headers=None):
    body = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers={**AUTH, **(headers or {})})


class TestMcpAuth:
    def test_requires_api_key(self, default_client):
        r = default_client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert r.status_code == 401

    def test_rejects_wrong_key(self, default_client):
        r = default_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"X-API-Key": "bad"},
        )
        assert r.status_code == 403


class TestInitialize:
    def test_returns_protocol_and_server_info(self, default_client):
        result = rpc(default_client, "initialize").json()["result"]
        assert result["protocolVersion"]
        assert result["serverInfo"]["name"]
        assert "tools" in result["capabilities"]

    def test_echoes_request_id(self, default_client):
        assert rpc(default_client, "initialize", req_id=99).json()["id"] == 99


class TestToolsList:
    def test_lists_callable_agents_only(self, default_client):
        tools = rpc(default_client, "tools/list").json()["result"]["tools"]
        assert {t["name"] for t in tools} == {"test-standard", "test-elevated"}

    def test_tools_declare_input_schema(self, default_client):
        tools = rpc(default_client, "tools/list").json()["result"]["tools"]
        for tool in tools:
            schema = tool["inputSchema"]
            assert schema["type"] == "object"
            assert "prompt" in schema["properties"]
            assert "prompt" in schema["required"]

    def test_trust_level_is_annotated(self, default_client):
        tools = {t["name"]: t for t in rpc(default_client, "tools/list").json()["result"]["tools"]}
        assert tools["test-elevated"]["annotations"]["trust_level"] == "elevated"


class TestToolsCall:
    def test_invokes_a_standard_agent(self, default_client):
        r = rpc(
            default_client,
            "tools/call",
            {"name": "test-standard", "arguments": {"prompt": "hi", "caller_id": "c1"}},
        )
        result = r.json()["result"]
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"
        assert "hi" in result["content"][0]["text"]

    def test_elevated_agent_denied_without_trust_header(self, default_client):
        r = rpc(
            default_client,
            "tools/call",
            {"name": "test-elevated", "arguments": {"prompt": "hi", "caller_id": "c2"}},
        )
        assert "error" in r.json()
        assert "elevated" in r.json()["error"]["message"].lower()

    def test_elevated_agent_rejected_even_with_forged_trust_header(self, default_client):
        # A standard key cannot self-promote by asserting the header — that
        # was the bypass this check previously had.
        r = rpc(
            default_client,
            "tools/call",
            {"name": "test-elevated", "arguments": {"prompt": "hi", "caller_id": "c3"}},
            headers={"X-Trust-Level": "elevated"},
        )
        assert "error" in r.json()

    def test_elevated_agent_allowed_for_elevated_key(self, default_client):
        r = rpc(
            default_client,
            "tools/call",
            {"name": "test-elevated", "arguments": {"prompt": "hi", "caller_id": "c3"}},
            headers={"X-API-Key": ELEVATED_KEY},
        )
        assert "result" in r.json()

    def test_non_dict_params_is_invalid_params(self, default_client):
        r = rpc(default_client, "tools/call", ["not", "a", "dict"])
        assert r.json()["error"]["code"] == -32602

    def test_unknown_tool_is_method_not_found(self, default_client):
        r = rpc(
            default_client,
            "tools/call",
            {"name": "nope", "arguments": {"prompt": "hi", "caller_id": "c4"}},
        )
        assert r.json()["error"]["code"] == -32601

    def test_hidden_agent_is_not_callable(self, default_client):
        r = rpc(
            default_client,
            "tools/call",
            {"name": "test-hidden", "arguments": {"prompt": "hi", "caller_id": "c5"}},
        )
        assert "error" in r.json()

    def test_missing_prompt_is_invalid_params(self, default_client):
        r = rpc(
            default_client,
            "tools/call",
            {"name": "test-standard", "arguments": {"caller_id": "c6"}},
        )
        assert r.json()["error"]["code"] == -32602

    def test_missing_name_is_invalid_params(self, default_client):
        r = rpc(default_client, "tools/call", {"arguments": {"prompt": "hi"}})
        assert r.json()["error"]["code"] == -32602

    def test_rate_limit_surfaces_as_json_rpc_error(self, client):
        c = client(RATE_LIMIT_RPM="2")
        args = {"name": "test-standard", "arguments": {"prompt": "hi", "caller_id": "rl"}}
        for _ in range(2):
            rpc(c, "tools/call", args)
        assert "error" in rpc(c, "tools/call", args).json()


class TestUnknownMethod:
    def test_returns_method_not_found(self, default_client):
        assert rpc(default_client, "no/such/method").json()["error"]["code"] == -32601
