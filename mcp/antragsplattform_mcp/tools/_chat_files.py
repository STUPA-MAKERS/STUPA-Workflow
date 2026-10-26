"""Files on a chat message: a ticket note, a to-do card comment or an application comment.

The platform has no upload route per thread. Each file goes up as a draft through the
draft upload of the wizard, `POST /apply/attachments` (multipart part `file`). The first
upload issues a draft token; every later upload of the same message sends it in the
header `X-Draft-Token`. A logged-in principal (an MCP token is one) needs no ALTCHA. The
create route of the message then binds the drafts with `attachmentIds` and `draftToken`
in one transaction.

The tool checks every file (existence, size, extension allowlist) before it uploads the
first one, so a bad path costs no upload. When an upload or the post fails, the tool
deletes the drafts it uploaded (`DELETE /apply/attachments/{id}`, best effort); the
hourly purge of the platform removes any that remain. The draft token never leaves this
module: it is not in a tool result.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ..client import ApiError
from ._common import api
from .meetings import _attachment_part

# `MAX_MESSAGE_ATTACHMENTS` of `backend/app/modules/files/schemas.py`. The tool checks it
# first, so an agent gets a clear message instead of a bare 422.
MAX_MESSAGE_FILES = 5

DRAFT_TOKEN_HEADER = "X-Draft-Token"


async def _discard(ids: list[str], token: str | None) -> None:
    """Delete uploaded drafts, best effort. A failure leaves them to the hourly purge."""
    if token is None:
        return
    for attachment_id in ids:
        with contextlib.suppress(ApiError):
            await api().delete(
                f"/apply/attachments/{attachment_id}",
                headers={DRAFT_TOKEN_HEADER: token},
            )


async def post_message(path: str, payload: dict[str, Any], file_paths: list[str] | None) -> Any:
    """Post a chat message, with its files uploaded as drafts first.

    Without `file_paths` this is a plain `POST path` with `payload`.

    Raises:
        ApiError: More than five files or a bad file (400, nothing is sent), or the
            error of an upload or of the post (the uploaded drafts are deleted).
    """
    if not file_paths:
        return await api().post(path, json=payload)
    if len(file_paths) > MAX_MESSAGE_FILES:
        raise ApiError(
            400,
            f"{len(file_paths)} files; a message takes at most {MAX_MESSAGE_FILES}",
        )
    parts = [_attachment_part(p, None) for p in file_paths]
    ids: list[str] = []
    token: str | None = None
    try:
        for name, data, mime in parts:
            headers = {DRAFT_TOKEN_HEADER: token} if token is not None else {}
            out = await api().post(
                "/apply/attachments",
                files={"file": (name, data, mime)},
                headers=headers,
            )
            token = token or out["draftToken"]
            ids.append(str(out["id"]))
        return await api().post(path, json={**payload, "attachmentIds": ids, "draftToken": token})
    except ApiError:
        await _discard(ids, token)
        raise
