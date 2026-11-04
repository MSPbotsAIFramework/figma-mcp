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
"""Comments: read, post (optionally as a reply) and, with confirmation, delete."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import FigmaClient
from ..config import API_BASE
from ._common import DESTRUCTIVE, READ_ONLY, WRITES, ClientFactory, Confirm, FileKey, compact, not_confirmed, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def figma_list_comments(file_key: FileKey) -> str:
        """List a file's existing comments (author, message, position, timestamps)."""

        async def action(client: FigmaClient) -> Any:
            return await client.get(API_BASE, f"files/{file_key}/comments")

        return await run_tool("figma_list_comments", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def figma_create_comment(
        file_key: FileKey,
        message: Annotated[str, Field(description="Comment text.", min_length=1)],
        comment_id: Annotated[str | None, Field(description="Reply to this existing comment id, instead of posting a new top-level comment.")] = None,
        client_meta: Annotated[dict | None, Field(description="Position to anchor the comment to (Figma's vector/frame-offset/region shape).")] = None,
    ) -> str:
        """Post a comment on a file, or a reply when comment_id is given.

        Only when the user explicitly asks to post that exact comment.
        """

        async def action(client: FigmaClient) -> Any:
            body = compact({"message": message, "comment_id": comment_id, "client_meta": client_meta})
            return await client.post(API_BASE, f"files/{file_key}/comments", body)

        return await run_tool("figma_create_comment", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def figma_delete_comment(
        file_key: FileKey,
        comment_id: Annotated[str, Field(description="Id of the comment to delete.", min_length=1)],
        confirm: Confirm = None,
    ) -> str:
        """Permanently delete a comment. Irreversible; needs confirm: true.

        Only when the user explicitly asks to delete that exact comment.
        """

        async def action(client: FigmaClient) -> Any:
            if confirm is not True:
                return not_confirmed(f"Permanently delete comment {comment_id} on file {file_key}")
            await client.delete(API_BASE, f"files/{file_key}/comments/{comment_id}")
            return {"done": True, "deleted_comment_id": comment_id}

        return await run_tool("figma_delete_comment", client_factory, action)
