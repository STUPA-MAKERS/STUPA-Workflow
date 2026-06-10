"""Thin async HTTP client around the platform API.

Attaches the OAuth bearer token; on a 401 it forces one token refresh/login and retries
once. Token acquisition (which may open a browser) runs in a worker thread so the async
event loop is never blocked. Errors are raised as :class:`ApiError` with the platform's
problem-detail message where available.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from . import auth
from .config import Config


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


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
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        resp = await self._client.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401:
            # Token rejected — force a fresh credential and retry exactly once.
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
