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
"""Identity: which Figma account the current token belongs to."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import FigmaClient
from ..config import API_BASE
from ._common import READ_ONLY, ClientFactory, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def figma_get_me() -> str:
        """Get the Figma account (id, email, handle) that the current X-Figma-Token belongs to."""

        async def action(client: FigmaClient) -> Any:
            return await client.get(API_BASE, "me")

        return await run_tool("figma_get_me", client_factory, action)
