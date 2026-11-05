# PRD-21325 · Code review

Status: frozen @ f4cb1c8

## Round 1 · 2026-11-05 · reviewed dev/PRD-21325 @ 8bde321 (base main @ 0f469f4)

Verdict: changes requested

### Scope

Full diff `origin/main...8bde321` (32 files, all new — this is a from-scratch MCP repo, see `docs/tickets/PRD-21325.md`). Verified independently in this round: `uv sync` + `uv run pytest` (96 passed, 0 failed, matches the Self-test report), README "MSPbots Connector" section byte-for-byte against `reference/readme-connector-section.md` (identical), Chinese-text grep (clean), tool count/annotations/description budgets (`tests/test_tools.py`, all pass), and the pagination contract of `figma_list_file_versions` against Figma's public API reference (see Finding 1).

### Findings

1. **[must-fix]** `src/figma_mcp/tools/_common.py:56` (`cursor_page`, used by `src/figma_mcp/tools/versions.py:29`) — `figma_list_file_versions` forwards the caller's `cursor` argument as a query parameter literally named `cursor` on `GET /v1/files/{file_key}/versions`. Figma's own REST API reference for this endpoint (`https://developers.figma.com/docs/rest-api/version-history-endpoints/`, and the `figma/rest-api-spec` OpenAPI spec) does not define a `cursor` parameter at all: the endpoint paginates via `page_size` (default 30, max 50), `before` and `after` (version ids), and the response's `pagination.next_page` / `prev_page` are opaque `String` fields documented with no stated relationship to a `cursor` query param. Sending an unrecognized `cursor=...` query string to this endpoint will be silently ignored by Figma (standard REST behavior for an unbound query param), so a second call with `cursor=<previous next_page>` returns the same first page again instead of advancing — pagination never actually works for a file with more versions than one page.
   - Design intent vs. reality: the tech design's "Data & API contract" section states cursors are forwarded "as-is instead of being translated into an offset model," and TC-FIGMA-008 explicitly requires "calling again with the returned `next_page` as `cursor` returns the next page, not the same one." TC-FIGMA-008 is marked "needs a real vendor account" / untested in the Self-test report, which is why this did not surface there — but the parameter-name mismatch is verifiable from Figma's public, unauthenticated API reference, independent of having a test account, so this is a code defect rather than an account-gated test gap.
   - Fix direction (to be decided by the dev leg, not prescribed here): either page using Figma's real `before` / `after` / `page_size` parameters directly instead of a generic opaque "cursor" abstraction, or confirm (with a real account, once available) that `next_page` is a ready-to-fetch full URL and follow that URL directly rather than re-wrapping its value into a new `cursor` parameter on a reconstructed path. Either way, `cursor_page()`'s current contract — a bare `cursor` query param — does not match any parameter Figma documents for this endpoint.
   - Evidence: `WebFetch` against `https://developers.figma.com/docs/rest-api/version-history-endpoints/` on 2026-11-05 returned the query parameters `page_size`, `before`, `after` for `GET /v1/files/{file_key}/versions` and the response shape `{"versions": Version[], "pagination": {"prev_page": String, "next_page": String}}`, with no `cursor` parameter mentioned anywhere on that page or in the `figma/rest-api-spec` OpenAPI source.

2. **[suggestion]** `src/figma_mcp/config.py:21-22` (`DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`) and `src/figma_mcp/tools/_common.py:48` (`PageSize`) are dead code — no tool in `tools/{folders,comments,images,files,versions}.py` accepts a page-size/limit argument, so these are defined but never referenced anywhere. This also means AC15's literal wording ("caps its page size (default ≤ 50, hard max ≤ 200) and its serialized result at 20000 characters") is only half-built: only the character-cap half (`dump_json_capped`, well covered by `tests/test_json_capped.py` / TC-FIGMA-019) exists; there is no record-count cap, because none of the wrapped Figma endpoints accept a page-size parameter to forward (the design's own "Data & API contract" section notes these endpoints return the full set upstream). Not blocking — the character cap achieves the actual goal (bounded response size) and is well tested — but worth either deleting the unused type/constants or updating AC15's wording to describe only the behavior that was actually built.

### Not re-litigated this round

Everything else reviewed clean against the tech design and `references/REVIEW.md`: credential handling (header-only, redacted `__repr__`, `contextvars` isolation with `finally` reset, tested for concurrent-tenant leakage), error envelope and status-code mapping (including the `401` fix found during the dev leg's own live verification), retry/backoff (reads only, `Retry-After`-aware, writes never retried), Dockerfile/compose (multi-stage, non-root, `curl`, `HEALTHCHECK`, `EXPOSE 8080` — structurally identical to the shipped `hudu-mcp` shape; `docker build` itself could not be run in either leg's sandbox, documented as an environment blind spot in both legs, not a code defect), and the two Open Questions (scope assumption, Figma-for-Government host) are appropriately left as non-blocking.

### Fixes — Round 1

Fixed at `dev/PRD-21325 @ 7033577` (on top of the reviewed `8bde321`). Only the must-fix (Finding 1) was addressed; Finding 2 is a non-blocking suggestion and was left as-is, per scope discipline for review rework.

1. **Finding 1 (must-fix) — fixed.** Re-verified Figma's documented contract for `GET /v1/files/{file_key}/versions` independently before fixing (`WebFetch` against `https://developers.figma.com/docs/rest-api/version-history-endpoints/` and the `figma/rest-api-spec` OpenAPI source, 2026-11-05): query parameters are `page_size`, `before`, `after` (all version ids); there is no `cursor` parameter. This matches the review's own finding.
   - `src/figma_mcp/tools/_common.py`: replaced `cursor_page()` (which always injected a literal `cursor=` query key) with `paged_get()`, which forwards exactly the params the caller builds and does not assume any shared pagination parameter across endpoints. Removed the now-unused `Cursor` type.
   - `src/figma_mcp/tools/versions.py`: `figma_list_file_versions` now takes `before` / `after` (Figma version ids) instead of `cursor`; added a module-level comment citing the same two sources, and a `VersionId` argument type local to this tool (it is not shared, unlike the removed `Cursor`).
   - `src/figma_mcp/server.py`, `README.md` (Tools section, not the byte-identical MSPbots Connector section): updated the pagination description to say before/after, not cursor.
   - `tests/test_api_client.py`: `test_list_file_versions_pages_with_cursor` encoded the broken assumption (it fed the mocked `next_page` URL back in as `cursor` and asserted the server received it under that name) — rewritten as `test_list_file_versions_pages_with_before_after`, asserting `before` and `after` are each forwarded as their own query parameter and that the other is absent.
   - **Test case changed**: `docs/tickets/PRD-21325.ac.json` TC-FIGMA-008's `text`/`steps` referred to calling again "with cursor set to ... next_page" — updated to "before (or after) set to the id of a version already seen". This changes the *procedure* a human will follow when a real vendor account is available, not the acceptance criterion: **AC8** only requires that `figma_list_file_versions` "returns the version history as a page of versions plus opaque `prev_page`/`next_page` cursors" — it does not name a request-side parameter. AC8 is unaffected and TC-FIGMA-008 still maps to it. `result`/`notes` still read `untested` / "needs a real vendor account" — this item remains account-gated and was not run live in this round.
   - Not done (deliberately, per the review's own list of options): did not attempt to follow `next_page` as a directly-fetchable URL, since that would require a real vendor account to confirm Figma's actual response shape for this field, which is not available in this environment (`notes` still carries "needs a real vendor account" on TC-FIGMA-008 for that reason).

### Retest (round 1 fix)

- `uv sync && uv run pytest` at `7033577`: **96 passed, 0 failed** (same count as the reviewed `8bde321` run — one test renamed, assertions extended, no test added or removed).
- `initialize` → `notifications/initialized` → `tools/list` over real HTTP with a placeholder `X-Figma-Token` header: 16 tools listed; `figma_list_file_versions`'s `inputSchema` now shows `before`/`after` (both optional strings), no `cursor` field. `GET /health` → 200. `POST /mcp` without `X-Figma-Token` → 401 naming the missing header, unchanged.
- Chinese-text grep (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): no output.
- README "MSPbots Connector" section vs `reference/readme-connector-section.md`: still byte-identical (not touched by this round's edits, which are in the separate "Tools" section below it).
- `gitleaks`: not installed in this sandbox, same as round 1; not run (environment gap, not a round-1 regression).

## Round 2 · 2026-11-05 · reviewed dev/PRD-21325 @ f4cb1c8 (base main @ 0f469f4)

Verdict: approved

### Scope

Diff `8bde321..f4cb1c8` (the round-1 reviewed commit to the current tip): 7 files — `README.md`, `docs/tickets/PRD-21325-review.md` (round 1 doc, not reviewed as code), `docs/tickets/PRD-21325.ac.json`, `src/figma_mcp/server.py`, `src/figma_mcp/tools/_common.py`, `src/figma_mcp/tools/versions.py`, `tests/test_api_client.py`.

### Round 1 must-fix — verified fixed

Finding 1 (`cursor_page` sending an undocumented `cursor` query param to `GET /v1/files/{file_key}/versions`): fixed correctly.

- Independently re-verified the upstream contract from a third source beyond the two the dev leg cited: fetched `figma/rest-api-spec`'s `openapi/openapi.yaml` directly (not just the rendered docs page, which this round's `WebFetch` found renders the parameter table as empty text — a tool/rendering gap, not evidence either way) and read the `GET /v1/files/{file_key}/versions` operation definition verbatim: it declares exactly `page_size`, `before`, `after` as query parameters and no `cursor`. This matches the round-1 finding and the fix.
- `src/figma_mcp/tools/_common.py`: `cursor_page()` (hardcoded `cursor=` query key) replaced by `paged_get()`, which forwards only the params the caller passes. The removed `Cursor` type and the old `cursor=` injection are gone; `grep -rniw cursor src/ tests/` shows no remaining functional reference (only doc comments and one unrelated mock URL string in `tests/test_json_capped.py`).
- `src/figma_mcp/tools/versions.py`: `figma_list_file_versions(file_key, before, after)` forwards both as independent, optional params — matches the spec's `before`/`after` semantics (mutually usable, not required).
- `tests/test_api_client.py::test_list_file_versions_pages_with_before_after`: asserts `before` and `after` are each sent as their own query param and that the other is absent on each call — a stronger assertion than round 1's single-param test (round 1's only checked `before`; this version separately exercises `after` too).
- Re-ran the full gate at `f4cb1c8` myself (not just trusted the dev leg's report): `uv sync && uv run pytest` → **96 passed, 0 failed**, same count as both the original and round-1-fix runs. Started the server locally (`uv run python -m figma_mcp`) and confirmed live: `GET /health` → 200; `POST /mcp initialize` with no `X-Figma-Token` → 401 `Missing header(s): X-Figma-Token`; with a placeholder token, `tools/list`'s `figma_list_file_versions` entry shows `before`/`after` (both optional strings) in `inputSchema` and no `cursor` field.
- README "MSPbots Connector" section: still byte-identical to `reference/readme-connector-section.md` (this round's edits are confined to the separate "Tools" table below it, consistent with the diff). Chinese-text grep: clean.

### Test case change (`docs/tickets/PRD-21325.ac.json`, TC-FIGMA-008)

Procedure wording changed from "cursor set to ... next_page" to "before (or after) set to the id of a version already seen". Confirmed non-expanding: AC8 itself ("returns the version history as a page of versions plus opaque `prev_page`/`next_page` cursors") names no request-side parameter, so the acceptance criterion is unaffected — only the human-executed steps changed to match the corrected API contract. `result`/`notes` still correctly read `untested` / "needs a real vendor account"; this was not newly claimed as passing.

### Finding 2 (round 1 suggestion) — left open, as expected

`PageSize`/`DEFAULT_PAGE_SIZE`/`MAX_PAGE_SIZE` dead code was explicitly left untouched this round ("per scope discipline" in the dev leg's own conclusion) — correct, it was filed as a non-blocking suggestion, not a must-fix.

### New findings this round

None. No new must-fix or suggestion surfaced in the round-2 diff.

### Not re-litigated this round

Everything outside the round-1-to-round-2 diff (credential handling, error envelope, retry/backoff, Dockerfile, SOP checklist, the two Open Questions) was already reviewed clean in round 1 and is untouched by this diff.
