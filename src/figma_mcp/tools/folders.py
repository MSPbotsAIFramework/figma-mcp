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
"""Teams and folders: where a team's files live (Figma's v2 folders endpoints)."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import FigmaClient
from ..config import API_BASE_V2
from ._common import READ_ONLY, ClientFactory, FolderId, TeamId, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def figma_list_folders(team_id: TeamId = None, folder_id: FolderId = None) -> str:
        """List a team's top-level folders, or a folder's subfolders. Give exactly one of team_id/folder_id."""

        async def action(client: FigmaClient) -> Any:
            if bool(team_id) == bool(folder_id):
                raise ValueError("Give exactly one of team_id or folder_id, not both and not neither.")
            if team_id:
                return await client.get(API_BASE_V2, f"teams/{team_id}/folders")
            return await client.get(API_BASE_V2, f"folders/{folder_id}/folders")

        return await run_tool("figma_list_folders", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def figma_list_folder_files(folder_id: FolderId) -> str:
        """List the files directly inside a folder."""

        async def action(client: FigmaClient) -> Any:
            if not folder_id:
                raise ValueError("folder_id is required.")
            return await client.get(API_BASE_V2, f"folders/{folder_id}/files")

        return await run_tool("figma_list_folder_files", client_factory, action)
