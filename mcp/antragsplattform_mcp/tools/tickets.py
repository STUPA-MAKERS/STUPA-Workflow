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
    kind: list[Literal["bug", "question", "idea", "barrier"]] | None = None,
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
    mentions: list[str] | None = None,
) -> dict:
    """Add a note to a ticket, optionally with files and mentions.

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
        mentions: Principal ids of the mentioned holders of `ticket.manage` (`GET
            /tickets/assignees`); they get a mail. Another id gives 422
            `mention_not_member`. Write a mention as "@Display Name" in `body`.
    """
    payload: dict[str, object] = {
        "body": body,
        **({"visibility": "public"} if public else {}),
        **({"mentions": mentions} if mentions else {}),
    }
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


@group.tool
async def tickets_note_edit(
    ticket_id: str, note_id: str, body: str, mentions: list[str] | None = None
) -> dict:
    """Change an own note of a ticket (403 `not_note_author` otherwise).

    `mentions` None keeps the stored mentions; a list replaces them, and only a person
    that the list adds gets the mail `ticket_mentioned`.
    """
    return await api().patch(
        f"/tickets/{ticket_id}/notes/{note_id}", json=params(body=body, mentions=mentions)
    )


@group.tool
async def tickets_note_delete(ticket_id: str, note_id: str) -> dict:
    """Delete an own note of a ticket and its files (403 `not_note_author` otherwise)."""
    await api().delete(f"/tickets/{ticket_id}/notes/{note_id}")
    return {"deleted": True}


@group.tool
async def tickets_counts() -> dict:
    """Count the tickets per status (`ticket.manage`)."""
    return await api().get("/tickets/counts")


@group.tool
async def tickets_assignees() -> list:
    """List the possible assignees: the active holders of `ticket.manage`, by name."""
    return await api().get("/tickets/assignees")


@group.tool
async def tickets_report(
    kind: Literal["bug", "question", "idea", "barrier"],
    title: str,
    body: str,
    file_paths: list[str] | None = None,
) -> dict:
    """Report a problem, a question, an idea or an accessibility barrier as the caller.

    The account of the caller is the reporter; the report and the answers show up in
    `tickets_mine`. Ask the user before you send a report. Files work as in
    `tickets_note`.

    Args:
        title: 1 to 200 characters.
        body: 1 to 10000 characters.
    """
    return await post_message(
        "/tickets",
        {"kind": kind, "title": title, "body": body, "context": {"route": "mcp"}},
        file_paths,
    )


@group.tool
async def tickets_mine(
    status: list[Literal["new", "in_progress", "done", "rejected"]] | None = None,
    kind: list[Literal["bug", "question", "idea", "barrier"]] | None = None,
    q: str | None = None,
) -> dict:
    """List the tickets that the caller reported, newest first."""
    return await api().get("/tickets/mine", params=params(status=status, kind=kind, q=q))


@group.tool
async def tickets_mine_get(ticket_id: str) -> dict:
    """Read an own ticket: the report, its files, the public notes and the status changes."""
    return await api().get(f"/tickets/mine/{ticket_id}")


@group.tool
async def tickets_mine_note(
    ticket_id: str, body: str = "", file_paths: list[str] | None = None
) -> dict:
    """Write a message on an own ticket; it is public and the team gets a mail.

    A blocked sender gets 403 `sender_blocked`. Files work as in `tickets_note`.
    """
    return await post_message(f"/tickets/mine/{ticket_id}/notes", {"body": body}, file_paths)


@group.tool
async def tickets_mine_note_edit(ticket_id: str, note_id: str, body: str) -> dict:
    """Change an own message on an own ticket (403 `not_note_author` otherwise)."""
    return await api().patch(f"/tickets/mine/{ticket_id}/notes/{note_id}", json={"body": body})


@group.tool
async def tickets_mine_note_delete(ticket_id: str, note_id: str) -> dict:
    """Delete an own message on an own ticket and its files."""
    await api().delete(f"/tickets/mine/{ticket_id}/notes/{note_id}")
    return {"deleted": True}


def register(mcp: FastMCP) -> None:
    """Register the ticket tool group."""
    group.register(mcp)
