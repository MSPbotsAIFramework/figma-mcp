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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import FigmaClient, FigmaCredentials
from .config import Settings

HEADER_TOKEN = "X-Figma-Token"
REQUIRED_HEADERS = [HEADER_TOKEN]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")

# Per-request isolation: the middleware sets this for the duration of one
# HTTP request and resets it in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[FigmaCredentials | None] = contextvars.ContextVar(
    "figma_credentials", default=None
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("figma_request_id", default="-")

INSTRUCTIONS = (
    "Figma holds design files organized into teams and folders; each file has "
    "a node tree (frames, groups, shapes, text) plus comments and version "
    "history.\n"
    "Usage:\n"
    "- Find files via figma_list_folders (team_id or folder_id) -> "
    "figma_list_folder_files; file keys feed every other tool.\n"
    "- Reading: figma_get_file_meta for name/thumbnail only; "
    "figma_get_file_nodes for a few known node ids; figma_get_file only when "
    "the whole tree (or a depth-limited slice) is actually needed, since it "
    "can be large.\n"
    "- figma_render_images turns node ids into viewable image URLs; "
    "figma_list_image_fills lists a file's embedded image downloads.\n"
    "- figma_list_file_versions pages with before/after: pass a version id "
    "from an already-seen page to fetch the versions right before/after it.\n"
    "Comments are visible to the file's collaborators: post and delete only "
    "on explicit user request. figma_delete_comment is permanent and needs "
    "confirm: true after the user approved that exact deletion."
)


def get_client_from_context() -> FigmaClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return FigmaClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


class GatewayCredentialsMiddleware:
    """Reads X-Figma-Token on /mcp requests; 401 when missing."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        token = _clean(request.headers.get(HEADER_TOKEN))
        if not token:
            await JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Missing header(s): {HEADER_TOKEN}",
                    "required_headers": REQUIRED_HEADERS,
                },
                status_code=401,
            )(scope, receive, send)
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(FigmaCredentials(token))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="figma-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], FigmaClient | None] = get_client_from_context

    from .tools import comments, files, folders, identity, images, versions

    for module in (identity, files, images, versions, folders, comments):
        module.register(mcp, client_factory)

    return mcp
