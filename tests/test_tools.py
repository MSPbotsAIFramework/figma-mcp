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
"""tools/list snapshot and error-envelope mapping. No network access. (TC-FIGMA-017 lives here too.)"""

import asyncio
import json

import pytest

from figma_mcp.server import INSTRUCTIONS, create_mcp_server

FILE_KEY = {"file_key"}
FILE_KEY_IDS = {"file_key", "ids"}

# Tool names are a public contract: existing agents and tenant connections
# depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "figma_get_me": set(),
    "figma_get_file": FILE_KEY,
    "figma_get_file_nodes": FILE_KEY_IDS,
    "figma_get_file_meta": FILE_KEY,
    "figma_render_images": FILE_KEY_IDS,
    "figma_list_image_fills": FILE_KEY,
    "figma_list_file_versions": FILE_KEY,
    "figma_list_folders": set(),
    "figma_list_folder_files": {"folder_id"},
    "figma_list_comments": FILE_KEY,
    "figma_create_comment": {"file_key", "message"},
    "figma_delete_comment": {"file_key", "comment_id"},
}
DELETE_TOOLS = {"figma_delete_comment"}
WRITE_TOOLS = {"figma_create_comment", "figma_delete_comment"}
READ_TOOLS = set(EXPECTED_TOOLS) - WRITE_TOOLS


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED_TOOLS)


def test_tool_count_is_within_budget(tools):
    assert len(tools) <= 20


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_tool_name_prefix(tools, name):
    assert name.startswith("figma_")


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations is not None
    assert annotations.readOnlyHint is (name in READ_TOOLS)
    assert bool(annotations.destructiveHint) is (name in DELETE_TOOLS)


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicit" in tools[name].description


@pytest.mark.parametrize("name", sorted(DELETE_TOOLS))
def test_delete_tools_take_confirm(tools, name):
    assert "confirm" in tools[name].inputSchema["properties"]


def test_image_scale_is_bounded(tools):
    scale = tools["figma_render_images"].inputSchema["properties"]["scale"]
    bounds = scale["anyOf"][0] if "anyOf" in scale else scale
    assert bounds["minimum"] == 1 and bounds["maximum"] == 4


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("figma_get_me", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
