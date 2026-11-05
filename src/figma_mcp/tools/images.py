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
"""Rendering nodes to images, and listing a file's embedded image fills."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import FigmaClient
from ..config import API_BASE
from ._common import READ_ONLY, ClientFactory, FileKey, ImageFormat, ImageScale, NodeIds, compact, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def figma_render_images(file_key: FileKey, ids: NodeIds, format: ImageFormat = None, scale: ImageScale = None) -> str:
        """Render the given node ids to image URLs (png/jpg/svg/pdf, default png)."""

        async def action(client: FigmaClient) -> Any:
            params = {"ids": ids, "format": format, "scale": scale}
            return await client.get(API_BASE, f"images/{file_key}", compact(params))

        return await run_tool("figma_render_images", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def figma_list_image_fills(file_key: FileKey) -> str:
        """List the download URLs of a file's embedded image fills, keyed by image reference."""

        async def action(client: FigmaClient) -> Any:
            return await client.get(API_BASE, f"files/{file_key}/images")

        return await run_tool("figma_list_image_fills", client_factory, action)
