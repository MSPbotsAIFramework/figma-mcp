# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Invalid arguments come back as the invalid_argument envelope, never a raised exception."""

import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolRequest, CallToolRequestParams

from figma_mcp import api_client
from figma_mcp.api_client import FigmaCredentials
from figma_mcp.server import _credentials_var, create_mcp_server

CREDS = FigmaCredentials("figd_test-token")


def _server():
    return create_mcp_server()


def _envelope(result):
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)["error"]


async def _call(monkeypatch, tool: str, args: dict, routes=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    http = httpx.AsyncClient(transport=httpx.MockTransport(routes or handler))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await _server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


# ---- TC-FIGMA-011 (AC9): both or neither of team_id/folder_id is invalid_argument ----


@pytest.mark.parametrize("args", [{}, {"team_id": "t1", "folder_id": "f1"}])
async def test_list_folders_requires_exactly_one_of_team_or_folder(monkeypatch, args):
    result = await _call(monkeypatch, "figma_list_folders", args)
    assert result["error"]["code"] == "invalid_argument"
    assert "exactly one" in result["error"]["message"]


async def test_missing_required_argument_is_invalid_argument():
    mcp = _server()
    error = _envelope(await mcp.call_tool("figma_get_file", {}))
    assert error["code"] == "invalid_argument" and error["retryable"] is False
    assert "file_key" in error["message"] and "Field required" in error["message"]


async def test_wrong_type_is_invalid_argument_without_echoing_the_value():
    mcp = _server()
    error = _envelope(await mcp.call_tool("figma_get_file_nodes", {"file_key": {"secret-value": 1}, "ids": ["1:2"]}))
    assert error["code"] == "invalid_argument" and "file_key" in error["message"]
    assert "secret-value" not in error["message"]


async def test_protocol_result_carries_the_envelope_like_other_tool_errors():
    mcp = _server()
    handler = mcp._mcp_server.request_handlers[CallToolRequest]
    request = CallToolRequest(method="tools/call", params=CallToolRequestParams(name="figma_get_file", arguments={}))
    result = (await handler(request)).root
    assert result.isError is False
    assert json.loads(result.content[0].text)["error"]["code"] == "invalid_argument"


async def test_unknown_tool_is_unchanged():
    with pytest.raises(ToolError, match="Unknown tool"):
        await _server().call_tool("no_such_tool", {})
