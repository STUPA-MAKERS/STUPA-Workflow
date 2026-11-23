"""A fake Paperless-ngx instance behind an `httpx.MockTransport`.

The fake keeps the document types, the tags, the custom fields, the consume tasks and
the documents in memory and answers the routes that the client of the platform calls. A
test reads `requests` to prove what the platform sent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.modules.paperless.client import PaperlessClient

HOST = "paperless.test"
BASE_URL = f"https://{HOST}"
TOKEN = "secret-token-0123456789"

_LISTS = ("document_types", "tags", "custom_fields")


@dataclass
class FakePaperless:
    """One Paperless instance in memory.

    Attributes:
        down: Each request fails with a connect error.
        status: Each request gets this error status.
        files: The PDF version of a document, which the download route answers.
        consume: `ok` makes a document of an upload at the first task read, `fail`
            makes the task fail, `wait` keeps it open.
    """

    down: bool = False
    status: int | None = None
    consume: str = "ok"
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])
    names: dict[str, dict[str, int]] = field(default_factory=lambda: {name: {} for name in _LISTS})
    uploads: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    documents: dict[int, dict[str, Any]] = field(default_factory=dict[int, dict[str, Any]])
    tasks: dict[str, int | None] = field(default_factory=dict[str, int | None])
    files: dict[int, bytes] = field(default_factory=dict[int, bytes])

    def _id(self) -> int:
        return 1 + sum(len(entries) for entries in self.names.values()) + len(self.documents)

    def name_of(self, where: str, entry_id: int) -> str:
        """The name of an entry of one of the lists."""
        return next(name for name, known in self.names[where].items() if known == entry_id)

    def _list(self, where: str, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            wanted = request.url.params.get("name__iexact", "").lower()
            ids = request.url.params.get("id__in")
            rows = [
                {"id": entry_id, "name": name}
                for name, entry_id in self.names[where].items()
                if (str(entry_id) in ids.split(",") if ids else name.lower() == wanted)
            ]
            return httpx.Response(200, json={"count": len(rows), "results": rows})
        body = json.loads(request.content)
        entry_id = self._id()
        self.names[where][body["name"]] = entry_id
        return httpx.Response(201, json={"id": entry_id, **body})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        text = request.content.decode("latin-1")

        def part(name: str) -> list[str]:
            marker = f'name="{name}"'
            return [
                chunk.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
                for chunk in text.split("--")
                if marker in chunk
            ]

        task_id = f"task-{len(self.uploads) + 1}"
        self.uploads.append(
            {
                "task": task_id,
                "title": part("title")[0].encode("latin-1").decode("utf-8"),
                "created": part("created")[0],
                "document_type": int(part("document_type")[0]),
                "tags": [int(tag) for tag in part("tags")],
                "bytes": part("document")[0],
            }
        )
        self.tasks[task_id] = None
        return httpx.Response(200, json=task_id)

    def _task(self, request: httpx.Request) -> httpx.Response:
        task_id = request.url.params["task_id"]
        if task_id not in self.tasks or self.consume == "wait":
            return httpx.Response(200, json=[{"task_id": task_id, "status": "STARTED"}])
        if self.consume == "fail":
            return httpx.Response(200, json=[{"task_id": task_id, "status": "FAILURE"}])
        if self.tasks[task_id] is None:
            upload = next(u for u in self.uploads if u["task"] == task_id)
            document_id = 100 + len(self.documents)
            self.documents[document_id] = {
                "id": document_id,
                "title": upload["title"],
                "created": upload["created"],
                "document_type": upload["document_type"],
                "tags": list(upload["tags"]),
                "custom_fields": [],
            }
            self.tasks[task_id] = document_id
        return httpx.Response(
            200,
            json=[
                {
                    "task_id": task_id,
                    "status": "SUCCESS",
                    "related_document": str(self.tasks[task_id]),
                }
            ],
        )

    def _document(self, document_id: int, request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            self.documents[document_id].update(json.loads(request.content))
        return httpx.Response(200, json=self.documents[document_id])

    def _search(self, request: httpx.Request) -> httpx.Response:
        """The documents whose title holds the query; without one, the newest first.

        ``id__in`` keeps only the documents with these numbers.
        """
        wanted = request.url.params.get("query", "").lower()
        ids = request.url.params.get("id__in")
        rows = [
            {key: row[key] for key in ("id", "title", "created", "document_type")}
            for row in self.documents.values()
            if wanted in str(row["title"]).lower() and (not ids or str(row["id"]) in ids.split(","))
        ]
        if "query" not in request.url.params:
            rows.reverse()
        return httpx.Response(200, json={"count": len(rows), "results": rows})

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request of the client."""
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("down", request=request)
        if self.status is not None:
            return httpx.Response(self.status, json={"detail": "error"})
        path = request.url.path.strip("/").removeprefix("api/")
        if path in _LISTS:
            return self._list(path, request)
        if path == "documents/post_document":
            return self._upload(request)
        if path == "tasks":
            return self._task(request)
        if path == "documents":
            return self._search(request)
        if path.endswith("/download"):
            return httpx.Response(200, content=self.files[int(path.split("/")[1])])
        return self._document(int(path.split("/")[1]), request)

    def client(
        self, base_url: str = BASE_URL, token: str = TOKEN, allowlist: tuple[str, ...] = (HOST,)
    ) -> PaperlessClient:
        """A client of the platform that speaks to this fake."""
        return PaperlessClient(
            base_url=base_url,
            token=token,
            allowlist=allowlist,
            client_factory=lambda _timeout: httpx.AsyncClient(
                transport=httpx.MockTransport(self.handle), follow_redirects=False
            ),
        )
