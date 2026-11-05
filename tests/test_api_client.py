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
"""Request shapes, retries and tool behaviour against a mocked Figma API."""

import json

import httpx
import pytest

from figma_mcp import api_client
from figma_mcp.api_client import FigmaClient, FigmaCredentials, FigmaError
from figma_mcp.config import API_BASE
from figma_mcp.server import _credentials_var, create_mcp_server

CREDS = FigmaCredentials("figd_test-token")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: replies by method + path below the API base."""

    def __init__(self, routes=None, default=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v1/").removeprefix("/v2/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(f"/{path}") and (method is None or r.method == method)]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> FigmaClient:
    return FigmaClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- TC-FIGMA-017 (AC14): status_code -> (code, retryable) mapping -----------------


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_status_to_code_mapping(status, code, retryable):
    envelope = json.loads(FigmaError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


# ---- client ------------------------------------------------------------------------


async def test_token_header_sent():
    rec = Recorder({"me": {"id": "1"}})
    await _client(rec).get(API_BASE, "me")
    request = rec.requests[0]
    assert request.headers["X-Figma-Token"] == "figd_test-token"
    assert str(request.url) == "https://api.figma.com/v1/me"


async def test_get_retries_5xx_but_writes_do_not():
    replies = iter([httpx.Response(502), httpx.Response(200, json={"id": "1"})])
    rec = Recorder({"GET me": lambda r: next(replies), "POST files/key1/comments": lambda r: httpx.Response(500, json={})})
    client = _client(rec)
    await client.get(API_BASE, "me")
    with pytest.raises(FigmaError):
        await client.post(API_BASE, "files/key1/comments", {"message": "hi"})
    assert len(rec.calls("me", "GET")) == 2 and len(rec.calls("files/key1/comments", "POST")) == 1


async def test_429_on_a_write_is_not_retried():
    # Design: reads retry on 429/5xx/network error; writes are never retried (never double-post/delete).
    rec = Recorder({"POST files/key1/comments": lambda r: httpx.Response(429, json={}, headers={"Retry-After": "1"})})
    client = _client(rec)
    with pytest.raises(FigmaError):
        await client.post(API_BASE, "files/key1/comments", {"message": "hi"})
    assert len(rec.calls("files/key1/comments", "POST")) == 1


async def test_html_error_pages_are_not_echoed(monkeypatch):
    rec = Recorder({"files/bad/meta": lambda r: httpx.Response(404, text="<html><body>Not Found</body></html>")})
    result = await _call(monkeypatch, rec, "figma_get_file_meta", {"file_key": "bad"})
    assert result["error"]["message"] == "Figma returned HTTP 404 for files/bad/meta"
    assert result["error"]["code"] == "not_found"


# ---- TC-FIGMA-020 (AC16): token is never echoed -------------------------------------


def test_credentials_repr_redacts_token():
    assert "figd_test-token" not in repr(CREDS)
    assert repr(CREDS) == "FigmaCredentials(token=<redacted>)"


async def test_token_not_in_error_message(monkeypatch):
    rec = Recorder({"files/bad/meta": lambda r: httpx.Response(403, json={"err": "Invalid token"})})
    result = await _call(monkeypatch, rec, "figma_get_file_meta", {"file_key": "bad"})
    assert "figd_test-token" not in json.dumps(result)
    assert result["error"]["code"] == "unauthorized"


# ---- tools built on the client -------------------------------------------------------


async def test_get_file_nodes_sends_comma_joined_ids(monkeypatch):
    rec = Recorder({"files/key1/nodes": {"nodes": {}}})
    await _call(monkeypatch, rec, "figma_get_file_nodes", {"file_key": "key1", "ids": ["1:2", "1:3"]})
    assert rec.requests[0].url.params["ids"] == "1:2,1:3"


async def test_render_images_defaults_and_scope(monkeypatch):
    rec = Recorder({"images/key1": {"images": {"1:2": "https://example.com/a.png"}}})
    result = await _call(monkeypatch, rec, "figma_render_images", {"file_key": "key1", "ids": ["1:2"], "format": "svg"})
    assert rec.requests[0].url.params["format"] == "svg"
    assert result["images"]["1:2"].endswith(".png")


async def test_create_comment_reply(monkeypatch):
    rec = Recorder({"POST files/key1/comments": {"id": "c2", "message": "reply"}})
    await _call(monkeypatch, rec, "figma_create_comment", {"file_key": "key1", "message": "reply", "comment_id": "c1"})
    assert body(rec.requests[0]) == {"message": "reply", "comment_id": "c1"}


async def test_delete_comment_needs_confirm(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "figma_delete_comment", {"file_key": "key1", "comment_id": "c1"})
    assert result["done"] is False and rec.requests == []
    result = await _call(monkeypatch, rec, "figma_delete_comment", {"file_key": "key1", "comment_id": "c1", "confirm": True})
    assert result == {"done": True, "deleted_comment_id": "c1"}
    assert rec.calls("files/key1/comments/c1", "DELETE")


async def test_list_folders_by_team(monkeypatch):
    rec = Recorder({"teams/t1/folders": {"folders": [{"id": "f1"}]}})
    result = await _call(monkeypatch, rec, "figma_list_folders", {"team_id": "t1"})
    assert result["folders"] == [{"id": "f1"}]
    assert rec.calls("teams/t1/folders", "GET")


async def test_list_folders_by_folder(monkeypatch):
    rec = Recorder({"folders/f1/folders": {"folders": [{"id": "f2"}]}})
    result = await _call(monkeypatch, rec, "figma_list_folders", {"folder_id": "f1"})
    assert result["folders"] == [{"id": "f2"}]


async def test_list_folder_files(monkeypatch):
    rec = Recorder({"folders/f1/files": {"files": [{"key": "k1"}]}})
    result = await _call(monkeypatch, rec, "figma_list_folder_files", {"folder_id": "f1"})
    assert result["files"] == [{"key": "k1"}]


async def test_list_file_versions_pages_with_before_after(monkeypatch):
    # PRD-21325 review round 1: Figma documents before/after/page_size for this endpoint, not a
    # "cursor" parameter (https://developers.figma.com/docs/rest-api/version-history-endpoints/,
    # figma/rest-api-spec OpenAPI source) -- an unrecognized cursor=... would be silently ignored.
    rec = Recorder(
        {
            "files/key1/versions": {
                "versions": [{"id": "v1"}],
                "pagination": {"prev_page": None, "next_page": "https://api.figma.com/v1/files/key1/versions?before=v1"},
            }
        }
    )
    result = await _call(monkeypatch, rec, "figma_list_file_versions", {"file_key": "key1"})
    assert result["versions"] == [{"id": "v1"}]
    assert result["next_page"].endswith("before=v1")
    assert "before" not in rec.requests[0].url.params  # first call: no paging id sent yet
    assert "after" not in rec.requests[0].url.params

    rec2 = Recorder({"files/key1/versions": {"versions": [{"id": "v2"}], "pagination": {}}})
    await _call(monkeypatch, rec2, "figma_list_file_versions", {"file_key": "key1", "before": "v1"})
    assert rec2.requests[0].url.params["before"] == "v1"
    assert "after" not in rec2.requests[0].url.params

    rec3 = Recorder({"files/key1/versions": {"versions": [{"id": "v0"}], "pagination": {}}})
    await _call(monkeypatch, rec3, "figma_list_file_versions", {"file_key": "key1", "after": "v1"})
    assert rec3.requests[0].url.params["after"] == "v1"
    assert "before" not in rec3.requests[0].url.params
