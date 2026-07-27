"""Thin async HTTP client around the platform API.

The client attaches the OAuth bearer token. On a 401 it forces one token refresh or login
and retries once. A token request can open a browser. That step therefore runs in a
worker thread and never blocks the async event loop. The client raises `ApiError` with
the problem-detail message of the platform where the platform sends one.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from . import auth
from .config import Config


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _safe_path(path: str) -> str:
    """Re-encode an API path that holds caller-supplied ids.

    Tool paths are plain f-strings like `/applications/{id}/votes`. The id goes in raw.
    httpx does not percent-encode `/` inside a segment. It also does not reject `..`, `?`
    or `#`. An id such as `../admin/audit` or `x?y=1` can therefore rewrite the route or
    smuggle a query string. This client always sends query parameters through the
    `params=` keyword argument and never puts them in the path. Every `?` or `#` in the
    path and every `.` or `..` segment is therefore illegitimate. This function rejects
    those. It percent-encodes anything else that does not belong in a single path
    segment, and it leaves the structural `/` separators intact. This is defense in
    depth. The server still authorizes the request through RBAC.

    Raises:
        ApiError: The path is relative, holds an illegal character, or traverses up.
    """
    if not path.startswith("/"):
        raise ApiError(400, f"invalid API path (must be absolute): {path!r}")
    if "?" in path or "#" in path or "\\" in path:
        raise ApiError(400, f"illegal character in API path segment: {path!r}")
    segments = path.split("/")
    encoded: list[str] = []
    for seg in segments:
        if seg in {".", ".."}:
            raise ApiError(400, f"path traversal is not allowed: {path!r}")
        # Encode any stray "/", "%" or whitespace that an id may carry. Plain route
        # names and UUIDs stay untouched.
        encoded.append(quote(seg, safe=""))
    return "/".join(encoded)


class ApiClient:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = httpx.AsyncClient(base_url=config.api, timeout=30)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _token(self, *, force_login: bool = False) -> str:
        return await asyncio.to_thread(
            auth.ensure_access_token, self._config, force_login=force_login
        )

    async def request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        path = _safe_path(path)
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        resp = await self._client.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401:
            # The server rejected the token. Get a fresh credential and retry once.
            token = await self._token(force_login=True)
            headers["Authorization"] = f"Bearer {token}"
            resp = await self._client.request(method, path, headers=headers, **kwargs)
        return self._unwrap(resp)

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            message = resp.text
            try:
                body = resp.json()
                message = body.get("detail") or body.get("title") or message
            except Exception:  # noqa: BLE001
                pass
            raise ApiError(resp.status_code, message)
        if resp.status_code == 204 or not resp.content:
            return {"status": "ok"}
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {"raw": resp.text}

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> Any:
        return await self.request("POST", path, **kw)

    async def patch(self, path: str, **kw: Any) -> Any:
        return await self.request("PATCH", path, **kw)

    async def put(self, path: str, **kw: Any) -> Any:
        return await self.request("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> Any:
        return await self.request("DELETE", path, **kw)
