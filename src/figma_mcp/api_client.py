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
"""Async client for the Figma REST API (v1 and v2)."""

import asyncio
import logging
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any

import httpx

from ._json import error_envelope

logger = logging.getLogger("figma_mcp.api")

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 20.0
# Whole-call budget including retries; the gateway times a tool call out at 120s.
_CALL_BUDGET_SECONDS = 100.0

# One connection pool for the process. It never holds credentials: the
# X-Figma-Token header is built per request from the caller's own token, so
# sharing the pool across tenants is safe.
_shared_http_client: httpx.AsyncClient | None = None


class _RejectAllCookies(DefaultCookiePolicy):
    """Never store or send a cookie: the HTTP client is shared by every tenant."""

    def set_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False

    def return_ok(self, cookie, request) -> bool:  # noqa: ANN001 - stdlib signature
        return False


def _no_cookies() -> CookieJar:
    # A plain CookieJar: httpx uses it as is (an httpx.Cookies would be copied into a default jar).
    return CookieJar(policy=_RejectAllCookies())


def _get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(cookies=_no_cookies(), timeout=_TIMEOUT)
    return _shared_http_client


# status_code -> (error code, retryable). 0 means no HTTP response at all
# (connection error or timeout). Figma's own docs only describe 403 for a bad
# token, but a live call against an invalid token observed 401 from the real
# API (2026-11-04 self-test, see Self-test in docs/tickets/PRD-21325.md) -- so
# both are mapped to "unauthorized". Our own middleware separately returns a
# gateway-level 401 when X-Figma-Token is missing entirely (AC2).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    429: ("rate_limited", True),
}


def classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    if status_code >= 400:
        return "invalid_argument", False
    return "upstream_error", True


class FigmaError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Figma API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = classify_status(self.status_code)
        return error_envelope(code, self.message, retryable)


@dataclass(frozen=True)
class FigmaCredentials:
    token: str

    def __repr__(self) -> str:  # never leak the token into logs or tracebacks
        return "FigmaCredentials(token=<redacted>)"


class FigmaClient:
    """Thin wrapper over the Figma API for one caller's personal access token."""

    def __init__(self, credentials: FigmaCredentials, http_client: httpx.AsyncClient | None = None):
        self._credentials = credentials
        self._http = http_client

    def _headers(self) -> dict[str, str]:
        return {"X-Figma-Token": self._credentials.token, "Accept": "application/json"}

    async def get(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
        return (await self.request("GET", base_url, path, params=params))[0]

    async def post(self, base_url: str, path: str, body: Any = None) -> Any:
        return (await self.request("POST", base_url, path, body=body))[0]

    async def delete(self, base_url: str, path: str) -> Any:
        return (await self.request("DELETE", base_url, path))[0]

    async def request(
        self,
        method: str,
        base_url: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> tuple[Any, httpx.Response]:
        http = self._http or _get_shared_http_client()
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        query = {k: _param_value(v) for k, v in (params or {}).items() if v is not None}
        headers = self._headers()
        started = time.monotonic()
        attempt = 0
        while True:
            t0 = time.monotonic()
            resp: httpx.Response | None = None
            error: FigmaError | None = None
            try:
                resp = await http.request(method, url, params=query, json=body, headers=headers)
                status = resp.status_code
            except httpx.TimeoutException:
                status, error = 0, FigmaError(0, f"Timed out calling Figma ({method} {path})")
            except httpx.RequestError as e:
                status, error = 0, FigmaError(0, f"Network error calling Figma ({method} {path}): {type(e).__name__}")

            logger.info(
                "figma_api method=%s path=%s status=%s ms=%d attempt=%d",
                method, path, status, (time.monotonic() - t0) * 1000, attempt,
            )

            # Reads are retried on 429/5xx/network error; a write (POST/DELETE) is never
            # retried, so a comment is never double-posted and a delete never double-fires.
            retryable = method == "GET" and (status == 429 or status == 0 or status >= 500)
            if retryable and attempt < _MAX_RETRIES:
                delay = _retry_delay(resp, attempt)
                if time.monotonic() - started + delay < _CALL_BUDGET_SECONDS:
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
            if error is not None:
                raise error
            assert resp is not None
            if resp.status_code >= 400:
                raise FigmaError(resp.status_code, _error_message(resp, path))
            if not resp.content or not resp.content.strip():
                return None, resp
            try:
                return resp.json(), resp
            except ValueError:
                return {"raw_response": resp.text[:2000]}, resp


def _param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return value


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), _MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_BACKOFF_SECONDS)


def _error_message(resp: httpx.Response, path: str) -> str:
    fallback = f"Figma returned HTTP {resp.status_code} for {path}"
    try:
        payload = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.lower().startswith("<"):
            return fallback  # an HTML error page, not useful to the agent
        return f"{fallback}: {text[:300]}" if text else fallback
    if isinstance(payload, dict):
        message = payload.get("err") or payload.get("message") or payload.get("error")
        if message:
            return f"{fallback}: {str(message)[:500]}"
    return fallback
