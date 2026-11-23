"""The HTTP client of the Paperless-ngx REST API.

Each call carries the token of the connection (§F/integrations/paperless/002513). The
client checks the host of the address against the deploy setting
`PAPERLESS_HOST_ALLOWLIST` before each call and follows no redirect
(§NF/security/network/002514), so a changed list also stops a stored address. The client
has no call with the method DELETE (§F/integrations/paperless/002522).

A failure is a `PaperlessError` with a short cause code and never the text of an
exception or of an answer, because such a text can hold the token or an internal address
(§NF/security/network/002515).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

#: The causes of a failed call. `blocked`: the host is not in the allowlist.
#: `unauthorized`: Paperless refuses the token. `status`: another error answer.
#: `format`: an answer that is not the JSON of the API.
ErrorCode = Literal[
    "blocked", "timeout", "unreachable", "redirect", "unauthorized", "status", "format"
]

#: The lists of Paperless in which the platform looks a name up and creates it.
NameList = Literal["document_types", "tags", "custom_fields"]

TIMEOUT_SECONDS = 20.0


class PaperlessError(Exception):
    """A call to Paperless failed. ``code`` is the short cause."""

    def __init__(self, code: ErrorCode) -> None:
        """Keep the cause code."""
        super().__init__(code)
        self.code: ErrorCode = code


def normalize_url(url: str) -> str:
    """Trim the address and drop the slash at its end."""
    return url.strip().rstrip("/")


def host_allowed(url: str, allowlist: Sequence[str]) -> bool:
    """Tell whether the address is `http` or `https` and its host is in the allowlist.

    An entry of the list is a host name, or a host name with a port. An empty list
    allows no address.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in ("http", "https") or not host or parts.username:
        return False
    allowed = frozenset(entry.strip().lower() for entry in allowlist if entry.strip())
    return host in allowed or parts.netloc.lower() in allowed


@dataclass(frozen=True, slots=True)
class Upload:
    """One file for Paperless with the data of its document."""

    filename: str
    content: bytes
    mime: str
    title: str
    created: date
    document_type: int
    tags: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskState:
    """The state of a consume task: the document number, a failure, or still open."""

    done: bool
    document_id: int | None = None
    failed: bool = False


def _client(timeout_seconds: float) -> httpx.AsyncClient:  # pragma: no cover - real HTTP
    return httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(timeout_seconds))


def _int(value: object) -> int | None:
    """Read a number that Paperless gives as a number or as a string of digits."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


@dataclass(frozen=True, slots=True)
class PaperlessClient:
    """Speak to one Paperless-ngx instance with the token of the connection.

    A test injects the HTTP client factory.
    """

    base_url: str
    token: str
    allowlist: tuple[str, ...]
    timeout_seconds: float = TIMEOUT_SECONDS
    client_factory: Callable[[float], httpx.AsyncClient] = _client

    async def _send(
        self,
        method: Literal["GET", "POST", "PATCH"],
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        timeout_seconds: float | None = None,
    ) -> object:
        """Send one request and return the JSON of the answer.

        Raises:
            PaperlessError: The host is not allowed, Paperless does not answer in time,
                or it answers with a redirect, an error or no JSON.
        """
        if not host_allowed(self.base_url, self.allowlist):
            raise PaperlessError("blocked")
        limit = timeout_seconds or self.timeout_seconds
        try:
            async with self.client_factory(limit) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    headers={
                        "Authorization": f"Token {self.token}",
                        "Accept": "application/json",
                    },
                    timeout=limit,
                )
        except httpx.TimeoutException as exc:
            raise PaperlessError("timeout") from exc
        except httpx.HTTPError as exc:
            raise PaperlessError("unreachable") from exc
        if 300 <= response.status_code < 400:
            raise PaperlessError("redirect")
        if response.status_code in (401, 403):
            raise PaperlessError("unauthorized")
        if not 200 <= response.status_code < 300:
            raise PaperlessError("status")
        try:
            return response.json()
        except ValueError as exc:
            raise PaperlessError("format") from exc

    async def check(self, timeout_seconds: float | None = None) -> None:
        """Read one document row, which proves the address and the token.

        Raises:
            PaperlessError: The connection does not work.
        """
        body = await self._send(
            "GET", "/api/documents/", params={"page_size": "1"}, timeout_seconds=timeout_seconds
        )
        if not isinstance(body, dict) or "results" not in body:
            raise PaperlessError("format")

    async def ensure(self, where: NameList, name: str) -> int:
        """Return the id of the entry with this name, and create the entry without one.

        A custom field is created with the data type `url`.

        Raises:
            PaperlessError: A call fails or the answer has no id.
        """
        found = await self._send("GET", f"/api/{where}/", params={"name__iexact": name})
        rows = found.get("results") if isinstance(found, dict) else None
        first = rows[0] if isinstance(rows, list) and rows else None
        known = _int(first.get("id")) if isinstance(first, dict) else None
        if known is not None:
            return known
        payload = {"name": name, **({"data_type": "url"} if where == "custom_fields" else {})}
        created = await self._send("POST", f"/api/{where}/", json=payload)
        new = _int(created.get("id")) if isinstance(created, dict) else None
        if new is None:
            raise PaperlessError("format")
        return new

    async def upload(self, upload: Upload) -> str:
        """Hand one file to Paperless and return the id of its consume task.

        Raises:
            PaperlessError: A call fails or the answer is no task id.
        """
        task = await self._send(
            "POST",
            "/api/documents/post_document/",
            data={
                "title": upload.title,
                "created": upload.created.isoformat(),
                "document_type": str(upload.document_type),
                "tags": [str(tag) for tag in upload.tags],
            },
            files={"document": (upload.filename, upload.content, upload.mime)},
        )
        if not isinstance(task, str) or not task:
            raise PaperlessError("format")
        return task

    async def task(self, task_id: str) -> TaskState:
        """Read the state of a consume task.

        Raises:
            PaperlessError: A call fails or the answer is not the list of the task.
        """
        body = await self._send("GET", "/api/tasks/", params={"task_id": task_id})
        rows = body.get("results") if isinstance(body, dict) else body
        row = rows[0] if isinstance(rows, list) and rows else None
        if not isinstance(row, dict):
            return TaskState(done=False)
        status = row.get("status")
        if status == "SUCCESS":
            document_id = _int(row.get("related_document"))
            return TaskState(done=True, document_id=document_id, failed=document_id is None)
        return TaskState(done=status == "FAILURE", failed=status == "FAILURE")

    async def _document(self, document_id: int) -> dict[str, Any]:
        body = await self._send("GET", f"/api/documents/{document_id}/")
        if not isinstance(body, dict):
            raise PaperlessError("format")
        return body

    async def set_link(self, document_id: int, field_id: int, url: str) -> None:
        """Set the custom field ``field_id`` of a document to ``url``.

        The other custom fields of the document stay.

        Raises:
            PaperlessError: A call fails.
        """
        document = await self._document(document_id)
        current = document.get("custom_fields")
        kept = [
            entry
            for entry in (current if isinstance(current, list) else [])
            if isinstance(entry, dict) and _int(entry.get("field")) != field_id
        ]
        await self._send(
            "PATCH",
            f"/api/documents/{document_id}/",
            json={"custom_fields": [*kept, {"field": field_id, "value": url}]},
        )

    async def add_tag(self, document_id: int, tag_id: int) -> None:
        """Add one tag to a document. The other tags of the document stay.

        Raises:
            PaperlessError: A call fails.
        """
        document = await self._document(document_id)
        current = document.get("tags")
        tags = [tag for tag in (current if isinstance(current, list) else []) if _int(tag)]
        if tag_id not in tags:
            await self._send(
                "PATCH", f"/api/documents/{document_id}/", json={"tags": [*tags, tag_id]}
            )


def document_url(base_url: str, document_id: int) -> str:
    """The address of a document in the web UI of Paperless."""
    return f"{base_url}/documents/{document_id}/details"
