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
"""File version history."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import FigmaClient
from ..config import API_BASE
from ._common import READ_ONLY, ClientFactory, FileKey, paged_get, run_tool

# Figma's documented query parameters for GET /v1/files/:key/versions are page_size, before and
# after (all version ids) -- there is no "cursor" parameter on this endpoint (PRD-21325 review
# round 1, verified against https://developers.figma.com/docs/rest-api/version-history-endpoints/
# and the figma/rest-api-spec OpenAPI source). before/after are exclusive: pass the id of a version
# already seen (e.g. the oldest one in the current page) to fetch the versions right before/after it.
VersionId = Annotated[str | None, Field(description="A version id from an already-seen page, to fetch the versions right before/after it.")]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def figma_list_file_versions(file_key: FileKey, before: VersionId = None, after: VersionId = None) -> str:
        """List a file's version history; pass a seen version id as before/after to page on."""

        async def action(client: FigmaClient) -> dict:
            return await paged_get(client, API_BASE, f"files/{file_key}/versions", "versions", {"before": before, "after": after})

        return await run_tool("figma_list_file_versions", client_factory, action)
