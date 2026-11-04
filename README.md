# Figma MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Figma](https://www.figma.com) REST
API. It lets an AI agent find a team's files, read a file's design structure and metadata,
render nodes to images, read version history, and read, post or delete comments.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: the credential arrives on every request as an HTTP header and is
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-Figma-Token` | Yes | string | none | - | Figma personal access token | `figd_your-token` |

Where to get it: in Figma, open **Settings → Personal access tokens** and generate one. Scope it
to at least `current_user:read`, `file_content:read`, `file_metadata:read`, `file_versions:read`,
`folders:read`, `file_comments:read`, and `file_comments:write` if comments will be used.

How the token is sent to Figma: every call goes to `https://api.figma.com/{v1|v2}/...` with the
token in the `X-Figma-Token` header.

A request to `/mcp` without the header gets HTTP 401 naming it as missing.

## Tools

All tools return a JSON string. Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "not_found", "message": "Figma returned HTTP 404 for files/abc/meta", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. Reads are retried with backoff on `429`, `5xx` and network
errors; writes (`figma_create_comment`, `figma_delete_comment`) are never retried, so a comment
is never double-posted or double-deleted.

| Area | Tools |
|---|---|
| Identity | `figma_get_me` |
| Files | `figma_get_file` (**file_key**, ids, depth, geometry), `figma_get_file_nodes` (**file_key**, **ids**), `figma_get_file_meta` (**file_key**) |
| Images | `figma_render_images` (**file_key**, **ids**, format, scale), `figma_list_image_fills` (**file_key**) |
| Versions | `figma_list_file_versions` (**file_key**, cursor) |
| Folders | `figma_list_folders` (team_id or folder_id, exactly one), `figma_list_folder_files` (**folder_id**) |
| Comments | `figma_list_comments` (**file_key**); **write**: `figma_create_comment` (**file_key**, **message**, comment_id, client_meta); **confirm**: `figma_delete_comment` (**file_key**, **comment_id**) |

`figma_list_file_versions` pages with Figma's own opaque cursor: pass the previous call's
`next_page` back in as `cursor` to continue; `figma_list_folders`/`figma_list_folder_files`/
`figma_list_comments`/`figma_list_image_fills` are not paginated upstream, but every tool still
caps its serialized result at 20000 characters and reports `has_more`/`truncated` when a result
had to be cut.

## Run locally

```bash
uv sync
uv run python -m figma_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t figma-mcp:dev .
docker run --rm -p 8080:8080 figma-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). The credential is never read
from the environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Figma-Token: figd_your-token" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# a file's metadata
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Figma-Token: figd_your-token" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"figma_get_file_meta","arguments":{"file_key":"abc123"}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **v1 scope.** No editing of design content: Figma's public REST API has no endpoint for that
  (content edits are Plugin-API-only, which runs inside the Figma app). No design-system/library
  browsing, no webhooks, no team/member administration — see the ticket's design document
  (`docs/tickets/PRD-21325.md`, "Decisions made by DEV01") for the per-group reasoning.
- **Personal access token, not OAuth2.** Simplest self-service credential for v1; no Figma app
  registration or token refresh needed.
- **v2 folders endpoints.** `figma_list_folders`/`figma_list_folder_files` use the v2
  `teams/:id/folders` and `folders/:id/folders`/`folders/:id/files` endpoints; Figma's own docs
  mark the older v1 teams/projects pair deprecated.
- **Deletes need confirmation.** `figma_delete_comment` takes `confirm: true` and otherwise
  returns a "not done" result.
- **No base-URL header.** Unlike per-instance vendors, Figma's API has one fixed host
  (`api.figma.com`); Figma for Government's different host is a documented open question, not
  built (no signal in this ticket that it applies).

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
