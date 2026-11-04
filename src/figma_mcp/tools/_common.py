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
"""Shared argument types, the list/record helpers, confirmation and the error-handling wrapper."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import FigmaClient, FigmaError
from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger("figma_mcp.tools")

ClientFactory = Callable[[], FigmaClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured", "Figma credentials are missing for this request (X-Figma-Token).", False
)

FileKey = Annotated[str, Field(description="Figma file key, from the file's URL (figma.com/file/<key>/...).", min_length=1)]
NodeIds = Annotated[list[str], Field(description="Node ids within the file, e.g. from a prior figma_get_file call.", min_length=1)]
OptionalNodeIds = Annotated[list[str] | None, Field(description="Node ids to scope the result to; omit for the whole file.")]
TeamId = Annotated[str | None, Field(description="Figma team id.", min_length=1)]
FolderId = Annotated[str | None, Field(description="Figma folder id.", min_length=1)]
ImageFormat = Annotated[str | None, Field(description="Image format (default png).", pattern="^(png|jpg|svg|pdf)$")]
ImageScale = Annotated[float | None, Field(description="Export scale, 1-4 (default 1).", ge=1, le=4)]
Cursor = Annotated[str | None, Field(description="Opaque cursor from a previous call's next_page, to continue paging.")]
PageSize = Annotated[int | None, Field(description=f"Records per page (default {DEFAULT_PAGE_SIZE}, max {MAX_PAGE_SIZE}).", ge=1, le=MAX_PAGE_SIZE)]
Confirm = Annotated[bool | None, Field(description="Must be true, set only after the user approved this exact deletion.")]


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


async def cursor_page(client: FigmaClient, base_url: str, path: str, key: str, params: dict[str, Any], cursor: str | None) -> dict:
    """GET a cursor-paginated Figma endpoint and pass its own prev_page/next_page tokens through.

    Figma's own cursors are opaque (not guaranteed to be offsets), so they are forwarded as-is
    instead of being translated into an offset model.
    """
    payload = await client.get(base_url, path, compact(params) | {"cursor": cursor})
    items = payload.get(key, []) if isinstance(payload, dict) else []
    pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
    return compact(
        {
            key: items,
            "count": len(items),
            "prev_page": pagination.get("prev_page"),
            "next_page": pagination.get("next_page"),
        }
    )


def not_confirmed(action: str) -> dict:
    return {
        "done": False,
        "action": action,
        "message": "Not done. Describe this deletion to the user and call again with confirm: true only after they approve it.",
    }


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[FigmaClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        result = await action(client)
    except FigmaError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if result is None:
        result = {"done": True}
    return result if isinstance(result, str) else dump_json_capped(result)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
