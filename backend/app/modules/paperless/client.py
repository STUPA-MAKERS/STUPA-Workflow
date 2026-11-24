"""The HTTP client of the Paperless-ngx REST API.

Each call carries the token of the connection (§F/integrations/paperless/002513). The
client checks the host of the address against the deploy setting
`PAPERLESS_HOST_ALLOWLIST` before each call and follows no redirect
(§NF/security/network/002514), so a changed list also stops a stored address. The client
has no call with the method DELETE (§F/integrations/paperless/002522).

`search` and `download` serve the insert from Paperless (§F/integrations/paperless/002527,
002528). `search` has a time limit of 5 seconds (§F/integrations/paperless/002529).
`search` and `document` serve the links to Paperless documents
(§F/integrations/paperless/002765, 002766).

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

from app.shared.ssrf import host_allowed

#: The causes of a failed call. `blocked`: the host is not in the allowlist.
#: `unauthorized`: Paperless refuses the token. `status`: another error answer.
#: `format`: an answer that is not the JSON of the API. `too_large`: a file over the
#: size limit of the caller.
ErrorCode = Literal[
    "blocked",
    "timeout",
    "unreachable",
    "redirect",
    "unauthorized",
    "status",
    "format",
    "too_large",
]

#: The lists of Paperless in which the platform looks a name up and creates it.
NameList = Literal["document_types", "tags", "custom_fields"]

TIMEOUT_SECONDS = 20.0

#: The time limit of the search of the insert (§F/integrations/paperless/002529).
SEARCH_TIMEOUT_SECONDS = 5.0

#: The most hits of one search.
SEARCH_LIMIT = 20


class PaperlessError(Exception):
    """A call to Paperless failed. ``code`` is the short cause."""

    def __init__(self, code: ErrorCode) -> None:
        """Keep the cause code."""
        super().__init__(code)
        self.code: ErrorCode = code


def normalize_url(url: str) -> str:
    """Trim the address and drop the slash at its end."""
    return url.strip().rstrip("/")


def address_allowed(url: str, allowlist: Sequence[str]) -> bool:
    """Tell whether the address is `http` or `https` and its host is in the allowlist.

    An entry of the list is a host name, or a host name with a port
    (`app.shared.ssrf.host_allowed`). An empty list allows no address.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme.lower() not in ("http", "https") or not host or parts.username:
        return False
    return host_allowed(host, parts.port, allowlist)


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


@dataclass(frozen=True, slots=True)
class DocumentHit:
    """One document of a search: its number, title, type name and date."""

    document_id: int
    title: str
    document_type: str | None = None
    created: date | None = None


def _date(value: object) -> date | None:
    """Read the day of a date or of a timestamp that Paperless gives as text."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


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

    async def _request(
        self,
        method: Literal["GET", "POST", "PATCH"],
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        timeout_seconds: float | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        """Send one request and return the answer with a success status.

        Raises:
            PaperlessError: The host is not allowed, Paperless does not answer in time,
                or it answers with a redirect or an error.
        """
        if not address_allowed(self.base_url, self.allowlist):
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
                    headers={"Authorization": f"Token {self.token}", "Accept": accept},
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
        return response

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
            PaperlessError: The request fails or the answer is no JSON.
        """
        response = await self._request(
            method,
            path,
            params=params,
            json=json,
            data=data,
            files=files,
            timeout_seconds=timeout_seconds,
        )
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

    async def _type_names(self, ids: Sequence[int], timeout_seconds: float) -> dict[int, str]:
        """Read the names of the document types with these ids."""
        if not ids:
            return {}
        body = await self._send(
            "GET",
            "/api/document_types/",
            params={"id__in": ",".join(str(i) for i in ids), "page_size": str(len(ids))},
            timeout_seconds=timeout_seconds,
        )
        rows = body.get("results") if isinstance(body, dict) else None
        return {
            type_id: name
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict)
            and (type_id := _int(row.get("id"))) is not None
            and isinstance(name := row.get("name"), str)
        }

    async def search(
        self, query: str, timeout_seconds: float = SEARCH_TIMEOUT_SECONDS
    ) -> list[DocumentHit]:
        """Search the documents by title and content, the best hits first.

        An empty query answers the documents that Paperless added last. The answer
        has at most `SEARCH_LIMIT` hits.

        Raises:
            PaperlessError: A call fails or the answer is not the list of the API.
        """
        text = query.strip()
        params = {
            "page_size": str(SEARCH_LIMIT),
            "fields": "id,title,created,document_type",
            **({"query": text} if text else {"ordering": "-added"}),
        }
        body = await self._send(
            "GET", "/api/documents/", params=params, timeout_seconds=timeout_seconds
        )
        return await self._hits(body, timeout_seconds)

    async def _hits(self, body: object, timeout_seconds: float) -> list[DocumentHit]:
        """Read the rows of a document list, with the name of each document type."""
        rows = body.get("results") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise PaperlessError("format")
        found = [
            (document_id, row)
            for row in rows[:SEARCH_LIMIT]
            if isinstance(row, dict) and (document_id := _int(row.get("id"))) is not None
        ]
        type_ids = sorted({t for _, row in found if (t := _int(row.get("document_type")))})
        names = await self._type_names(type_ids, timeout_seconds)
        return [
            DocumentHit(
                document_id=document_id,
                title=str(row.get("title") or document_id),
                document_type=names.get(_int(row.get("document_type")) or 0),
                created=_date(row.get("created")),
            )
            for document_id, row in found
        ]

    async def document(
        self, document_id: int, timeout_seconds: float = SEARCH_TIMEOUT_SECONDS
    ) -> DocumentHit | None:
        """Read the title, the type and the date of one document, or None without it.

        The read is a list with a filter by the number, so a document that Paperless
        does not have is an empty answer and not an error.

        Raises:
            PaperlessError: A call fails or the answer is not the list of the API.
        """
        body = await self._send(
            "GET",
            "/api/documents/",
            params={
                "id__in": str(document_id),
                "page_size": "1",
                "fields": "id,title,created,document_type",
            },
            timeout_seconds=timeout_seconds,
        )
        hits = await self._hits(body, timeout_seconds)
        return next((hit for hit in hits if hit.document_id == document_id), None)

    async def title(self, document_id: int) -> str:
        """Read the title of one document.

        Raises:
            PaperlessError: A call fails.
        """
        document = await self._document(document_id)
        return str(document.get("title") or document_id)

    async def download(self, document_id: int, max_bytes: int) -> bytes:
        """Read the PDF version of one document, the archive version of Paperless.

        The request accepts ``*/*``: Paperless matches the Accept header of the download
        route against its JSON renderers before it sends the file, so ``application/pdf``
        gets 406. The size check and the PDF check of the caller still hold.

        Raises:
            PaperlessError: A call fails, or the file has more than ``max_bytes``
                (`too_large`).
        """
        response = await self._request(
            "GET", f"/api/documents/{document_id}/download/", accept="*/*"
        )
        if len(response.content) > max_bytes:
            raise PaperlessError("too_large")
        return response.content


def document_url(base_url: str, document_id: int) -> str:
    """The address of a document in the web UI of Paperless."""
    return f"{base_url}/documents/{document_id}/details"
