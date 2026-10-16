"""Ticket tools: the reported problems, questions and ideas of the help menu.

Every tool needs the global permission `ticket.manage` and the scope `tickets:write`.
A reporter never reads a ticket, so there is no reporter tool. A note can carry files
(`file_paths`, uploaded as drafts first, see `_chat_files`). "Absender sperren" blocks
the reporter of a ticket: a later report of that sender gets a number and is dropped.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_patch
from ._chat_files import post_message
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def tickets_list(
    status: list[Literal["new", "in_progress", "done", "rejected"]] | None = None,
    kind: list[Literal["bug", "question", "idea"]] | None = None,
    assignee: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List the tickets, newest first, offset-paged.

    Args:
        status: Keep only these statuses.
        kind: Keep only these kinds.
        assignee: A principal id, `me` or `none`.
        q: Matches the title, the body, the number (`T-0040`, `40`) and the reporter.
    """
    return await api().get(
        "/tickets",
        params=params(
            status=status, kind=kind, assignee=assignee, q=q, limit=limit, offset=offset
        ),
    )


@group.tool
async def tickets_get(ticket_id: str) -> dict:
    """Get one ticket with body, technical context, attachments, notes and events.

    Each note lists its `attachments` with `scanState`; download a clean one with
    `download_attachment`. `senderBlocked` tells whether the reporter is blocked.
    """
    return await api().get(f"/tickets/{ticket_id}")


@group.tool
async def tickets_note(
    ticket_id: str,
    body: str = "",
    file_paths: list[str] | None = None,
    public: bool = False,
) -> dict:
    """Add a note to a ticket, optionally with files.

    A note is internal: the reporter never sees it. With `public` the reporter account
    reads it (and its files) in its own view of the ticket; a report without an account
    has nobody to read it.

    Each file in `file_paths` (a local path on the machine of the MCP server, at most 5
    per note) goes up as a draft through `POST /apply/attachments`; the note then binds
    the drafts. Allowed types and the 10 MB cap are those of `upload_attachment`. The
    note in the result lists `attachments` (`id`, `filename`, `mime`, `size`,
    `scanState`: `scanning`, `clean` or `quarantined`); download a clean one with
    `download_attachment`. Files on an anonymized ticket give 422 `ticket_anonymized`.
    A failed upload or post deletes the drafts already uploaded.

    Args:
        body: Markdown, up to 10000 characters; empty only with at least one file.
        file_paths: Local files to attach.
        public: Show the note to the reporter account.
    """
    payload: dict[str, object] = {"body": body}
    if public:
        payload["visibility"] = "public"
    return await post_message(f"/tickets/{ticket_id}/notes", payload, file_paths)


@group.tool
async def tickets_update(ticket_id: str, patch: S.TicketPatch) -> dict:
    """Change the status, the assignee or the kind of a ticket.

    Each change writes an event. An assignee without ticket.manage gives 422
    `assignee_not_allowed`. `duplicateOfId` goes only with status `rejected`
    (422 `duplicate_invalid` otherwise). With status `done` or `rejected`,
    `completeTodos: true` also completes the open linked to-dos the caller can write.
    """
    return await api().patch(f"/tickets/{ticket_id}", json=dump_patch(patch))


@group.tool
async def tickets_block_sender(ticket_id: str) -> dict:
    """Block the reporter of a ticket ("Absender sperren").

    The block targets the account of the reporter, or the lowercased e-mail of a guest
    report. A later report of that sender still gets a ticket number, but no ticket,
    no mail and no count; the block counts it as a hit. Idempotent. An anonymized
    ticket gives 409 `ticket_sender_unknown`, the own account 422 `sender_is_self`.

    Returns:
        The ticket, with `senderBlocked: true`.
    """
    return await api().post(f"/tickets/{ticket_id}/block-sender")


@group.tool
async def tickets_unblock_sender(ticket_id: str) -> dict:
    """Lift the block of the reporter of a ticket. Without a block nothing changes.

    An anonymized ticket gives 409 `ticket_sender_unknown`; lift such a block with
    `tickets_delete_blocked_sender`.

    Returns:
        The ticket, with `senderBlocked: false`.
    """
    return await api().delete(f"/tickets/{ticket_id}/block-sender")


@group.tool
async def tickets_blocked_senders() -> list:
    """List the blocked senders, newest first.

    Each entry: `id` (the block), `kind` (`principal` or `email`), `person`, `email`,
    `blockedBy`, `blockedAt`, `sourceTicket` (`id`, `number`; null after the ticket is
    gone), `hitCount` (reports dropped since the block) and `lastHitAt`.
    """
    return await api().get("/tickets/blocked-senders")


@group.tool
async def tickets_delete_blocked_sender(block_id: str) -> dict:
    """Lift one block by its id from `tickets_blocked_senders`. Unknown id: 404."""
    return await api().delete(f"/tickets/blocked-senders/{block_id}")


def register(mcp: FastMCP) -> None:
    """Register the ticket tool group."""
    group.register(mcp)
