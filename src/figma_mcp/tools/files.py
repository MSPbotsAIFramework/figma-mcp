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
"""File content and metadata: the design node tree, scoped nodes, and lightweight metadata."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import FigmaClient
from ..config import API_BASE
from ._common import READ_ONLY, ClientFactory, FileKey, NodeIds, OptionalNodeIds, compact, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def figma_get_file(
        file_key: FileKey,
        ids: OptionalNodeIds = None,
        depth: Annotated[int | None, Field(description="Limit how many levels of the node tree are returned.", ge=1)] = None,
        geometry: Annotated[str | None, Field(description="Set to 'paths' to include vector geometry.", pattern="^paths$")] = None,
    ) -> str:
        """Get a file's document tree; scope it with ids or depth when the whole tree is not needed."""

        async def action(client: FigmaClient) -> Any:
            params = {"ids": ids, "depth": depth, "geometry": geometry}
            return await client.get(API_BASE, f"files/{file_key}", compact(params))

        return await run_tool("figma_get_file", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def figma_get_file_nodes(file_key: FileKey, ids: NodeIds) -> str:
        """Get only the given node ids (and their subtrees) from a file, not the whole document."""

        async def action(client: FigmaClient) -> Any:
            return await client.get(API_BASE, f"files/{file_key}/nodes", {"ids": ids})

        return await run_tool("figma_get_file_nodes", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def figma_get_file_meta(file_key: FileKey) -> str:
        """Get a file's name, thumbnail URL and last-modified time, without its document tree."""

        async def action(client: FigmaClient) -> Any:
            return await client.get(API_BASE, f"files/{file_key}/meta")

        return await run_tool("figma_get_file_meta", client_factory, action)
