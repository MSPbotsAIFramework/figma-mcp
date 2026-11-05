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
"""Size-capped results never skip records: shorten fields first, then cut without a skipping continuation (AC15)."""

import json

from figma_mcp._json import MAX_CHARS, dump_json_capped


def _load(text: str) -> dict:
    assert len(text) <= MAX_CHARS
    return json.loads(text)


def test_small_result_is_unchanged():
    data = {"comments": [{"id": "c1"}], "count": 1}
    assert _load(dump_json_capped(data)) == {"comments": [{"id": "c1"}], "count": 1}


def test_long_fields_are_shortened_and_every_record_kept():
    rows = [{"id": f"c{i}", "message": "x" * 4800} for i in range(25)]
    out = _load(dump_json_capped({"comments": rows, "count": 25}))
    assert [r["id"] for r in out["comments"]] == [f"c{i}" for i in range(25)]
    assert out["count"] == 25
    assert out["fields_truncated"] is True and "truncated" not in out


# ---- TC-FIGMA-019 (AC15): an oversized figma_list_comments-shaped response is cut, ----
# ---- not silently dropped, and reports has_more/truncated -----------------------------


def test_oversized_list_is_truncated_with_has_more():
    rows = [{"id": f"c{i}", **{f"f{j}": f"value-{j:04d}" for j in range(120)}} for i in range(60)]
    data = {"comments": rows, "count": 60}
    out = _load(dump_json_capped(data))
    n = len(out["comments"])
    assert 0 < n < 60
    assert out["count"] == n and out["original_count"] == 60 and out["retry_page_size"] == n
    assert out["has_more"] is True and out["truncated"] is True
    assert [r["id"] for r in out["comments"]] == [f"c{i}" for i in range(n)]


def test_cut_cursor_pages_drop_prev_and_next_page():
    rows = [{"id": f"v{i}", **{f"f{j}": f"value-{j:04d}" for j in range(120)}} for i in range(60)]
    data = {"versions": rows, "count": 60, "prev_page": None, "next_page": "https://api.figma.com/v1/x?cursor=abc"}
    out = _load(dump_json_capped(data))
    assert "next_page" not in out and "prev_page" not in out
    assert out["truncated"] is True


def test_single_oversized_record_is_shortened_not_dropped():
    record = {"id": "f1", "name": "Big file", "document": {"nested": "x" * 30_000}}
    out = json.loads(dump_json_capped(record))
    assert (out["id"], out["name"]) == ("f1", "Big file")
    assert out["fields_truncated"] is True
    assert len(json.dumps(out)) <= MAX_CHARS
