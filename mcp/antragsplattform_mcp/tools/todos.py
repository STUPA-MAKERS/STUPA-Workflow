"""To-do board tools: boards, member entries, cards, moves and comments.

A person has a role on a board: `read`, `edit` or `manage`. A gremium board: each active
member of the gremium edits, a member whose gremium role holds `todo.configure` manages,
and its extra entries (gremien or persons) add their roles. A free board (kind `free`)
follows its entries only. The personal board is for its owner only, a team board for the
holders of its permission; an admin manages every gremium and free board. The global
`todo.all` reads and writes, `todo.read_all` only reads every gremium, free and team
board (never a personal one). An unreadable board or card is 404; a card write on a
board that is only readable is 403 `todo_write_required`; a change of the settings or
the entries without `manage` is 403 `todo_configure_required`. The token reads with the
scope `read` (`todo.read_all`) or `todos:write` and writes with `todos:write`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._chat_files import post_message
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def todo_boards(gremium_id: str | None = None, archived: bool | None = None) -> list:
    """List the to-do boards the caller can read.

    The order is the personal board ("Meine To-Dos", created on the first call), the
    gremium boards by name, the free boards by name, then the team boards. Each entry
    carries `canWrite`, `canConfigure`, `openCount` (cards not archived and not in the
    done column) and `agendaGremiumIds` (the gremien whose meetings take its cards).

    Args:
        gremium_id: Only the board of this gremium.
        archived: True lists the archived free boards that the caller manages instead.
    """
    return await api().get(
        "/todos/boards", params=params(gremiumId=gremium_id, archived=archived or None)
    )


@group.tool
async def todo_board_create(name: str, entries: list[S.TodoBoardEntryIn] | None = None) -> dict:
    """Create a free board with the columns Offen, In Arbeit, Wartet, Erledigt.

    Needs an admin or the global permission `todo.create_board` (403
    `board_create_required`). The caller becomes a member with `manage`. A person entry
    gets the mail `todo_board_added`. A double entry is 422 `entry_duplicate`, an entry
    with both or no target 422 `entry_target`.

    Args:
        name: 1 to 120 characters.
        entries: The first gremien and persons, each with a role (default `edit`).
    """
    body = {"name": name, "entries": [e.model_dump(exclude_none=True) for e in entries or []]}
    return await api().post("/todos/boards", json=body)


@group.tool
async def todo_board_entries(board_id: str) -> list:
    """List the member entries of a board: gremien first, then persons, each by name.

    The own gremium of a gremium board comes first with `fixed: true` and no `id`; it
    cannot be changed. Each entry has `id`, `kind` (`gremium` | `person`), `targetId`,
    `name` and `role`.
    """
    return await api().get(f"/todos/boards/{board_id}/entries")


@group.tool
async def todo_board_entry_add(board_id: str, entry: S.TodoBoardEntryIn) -> list:
    """Add a gremium or a person to a gremium board or a free board (needs `manage`).

    A gremium entry stands for the members of the gremium at the time of each read. 409
    `entry_exists` for a target on the board, 409 `own_gremium_entry` for the own gremium
    of a gremium board, 422 `entries_not_supported` on a personal or team board. Returns
    all entries.
    """
    return await api().post(
        f"/todos/boards/{board_id}/entries", json=entry.model_dump(exclude_none=True)
    )


@group.tool
async def todo_board_entry_update(board_id: str, entry_id: str, role: S.TodoEntryRole) -> list:
    """Change the role of an entry (needs `manage`).

    The last `manage` entry of a free board stays: 409 `last_manager`. Returns all
    entries.
    """
    return await api().patch(f"/todos/boards/{board_id}/entries/{entry_id}", json={"role": role})


@group.tool
async def todo_board_entry_remove(board_id: str, entry_id: str) -> list:
    """Remove an entry (needs `manage`; 409 `last_manager`). Returns all entries."""
    return await api().delete(f"/todos/boards/{board_id}/entries/{entry_id}")


@group.tool
async def todo_board_archive(board_id: str) -> dict:
    """Archive a free board (needs `manage`): hidden from every list and read-only.

    A write on an archived board is 409 `board_archived`. Restore it with
    `todo_board_restore`; list the archived boards with `todo_boards(archived=True)`.
    """
    return await api().post(f"/todos/boards/{board_id}/archive")


@group.tool
async def todo_board_restore(board_id: str) -> dict:
    """Restore an archived free board (needs `manage`)."""
    return await api().post(f"/todos/boards/{board_id}/restore")


@group.tool
async def todo_board_delete(board_id: str) -> dict:
    """Delete an archived free board with all its cards, comments and files.

    Admins only (403 `board_delete_admin_only`); a board that is not archived is 409
    `board_not_archived`. This cannot be undone.
    """
    await api().delete(f"/todos/boards/{board_id}")
    return {"deleted": board_id}


@group.tool
async def todo_board(board_id: str) -> dict:
    """Get one board with its columns (by position), labels and the cards not archived.

    The cards carry no description; read one with `todo_card_get`. The column with
    `isDone: true` is the done column: a card in it is done.
    """
    return await api().get(f"/todos/boards/{board_id}")


@group.tool
async def todo_my_cards() -> list:
    """List my cards on the other boards, grouped by board.

    Each entry is a board that the caller can read and on which live cards (done
    ones too) name the caller as an assignee: `id`, `name`, `kind`, `gremiumId`,
    `canWrite`, all `columns` in their order (`cardCount` counts my cards there), the
    board `labels` and only my `cards`. The personal board is left out; read it with
    `todo_board`. A board that the caller can no longer read is left out, also when
    a card of it still names the caller. Move a card with `todo_card_move` on its own
    board, and with `todo_card_transfer` to another board.
    """
    return await api().get("/todos/mine/boards")


@group.tool
async def todo_all_boards() -> list:
    """List every board that the caller can read, with all its live cards.

    The meta-board "Alle": the personal board first (the call creates it), then the
    gremium boards by name, then the team boards. Each entry has `id`, `name`, `kind`,
    `gremiumId`, `canWrite` (false on a board that the caller only reads), all
    `columns` in their order (`cardCount` counts the live cards there), the board
    `labels` and every live `card`, done ones too; archived cards are left out. Move a
    card with `todo_card_move` on its own board, and with `todo_card_transfer` to
    another board.
    """
    return await api().get("/todos/all/boards")


@group.tool
async def todo_card_get(card_id: str) -> dict:
    """Get one card with description, checklist, links, comments and events.

    Each comment lists its `attachments` with `scanState`; download a clean one with
    `download_attachment`.

    `version` is the optimistic lock that `todo_card_update` needs. A link whose
    target the caller cannot read has `accessible: false` and no title.
    """
    return await api().get(f"/todos/cards/{card_id}")


@group.tool
async def todo_card_create(card: S.TodoCardCreate) -> dict:
    """Create a card on a board, by default at the end of the first column.

    Assignees must be members of the board (422 `assignee_not_allowed`), labels must
    belong to the board (422 `label_not_on_board`) and every link target must be
    readable for the caller (422 `link_target_not_found`).
    """
    return await api().post("/todos/cards", json=dump_create(card))


@group.tool
async def todo_card_update(card_id: str, patch: S.TodoCardPatch) -> dict:
    """Patch the title, description or due date of a card.

    `version` is required: pass the value from `todo_card_get`. A changed card gives
    409 `card_version_conflict`; read it again and retry. An explicit null clears the
    description or the due date. Moves, assignees, labels, checklist, links and
    comments do not change the version.
    """
    return await api().patch(f"/todos/cards/{card_id}", json=dump_patch(patch))


@group.tool
async def todo_card_move(
    card_id: str,
    column_id: str,
    before_id: str | None = None,
    after_id: str | None = None,
) -> dict:
    """Move a card into a column, at the end or next to a neighbor card.

    A move into the done column marks the card done and notes it on every linked
    ticket; a move out of it reopens the card. A neighbor that is not in that column
    gives 422 `rank_neighbors_invalid`.

    Args:
        column_id: The target column, also the current one to reorder.
        before_id: Place the card directly above this card.
        after_id: Place the card directly below this card.
    """
    return await api().post(
        f"/todos/cards/{card_id}/move",
        json=params(columnId=column_id, beforeId=before_id, afterId=after_id),
    )


@group.tool
async def todo_card_transfer(
    card_id: str,
    board_id: str,
    column_id: str | None = None,
    before_id: str | None = None,
    after_id: str | None = None,
) -> dict:
    """Move a card into a column of another board, by default to its end.

    Labels are per board: a label stays when the target board has a label with the
    same name (case-insensitive), else it is dropped. No label is created on the
    target. Assignees who are not members of the target board are dropped, without a
    mail. Links, comments, the checklist and the history stay with the card. The
    done column of the target marks the card done; another column reopens it.
    A card of the caller's own personal board without assignees gets the caller as
    assignee when the caller is a member of the target board. A card of a shared
    board (gremium or team) never moves into a personal board.
    Errors: 404 for a card or target board that the caller cannot read, 403
    `todo_write_required` (a board that the caller reads but cannot write) or
    `transfer_to_personal` (a shared board into a personal board), 422
    `transfer_same_board` (use `todo_card_move`), `column_not_on_board` or
    `rank_neighbors_invalid` (a neighbor outside the target column), 409
    `card_archived` or `card_moved` (read the card again).

    Args:
        board_id: The target board.
        column_id: A column of the target board (default: its first column).
        before_id: The card below the new place, in the target column.
        after_id: The card above the new place, in the target column.
    """
    return await api().post(
        f"/todos/cards/{card_id}/transfer",
        json=params(
            boardId=board_id, columnId=column_id, beforeId=before_id, afterId=after_id
        ),
    )


@group.tool
async def todo_comment(
    card_id: str,
    body: str = "",
    mentions: list[str] | None = None,
    file_paths: list[str] | None = None,
) -> dict:
    """Add a comment to a card, optionally with files.

    Each file in `file_paths` (a local path on the machine of the MCP server, at most 5
    per comment) goes up as a draft through `POST /apply/attachments`; the comment then
    binds the drafts. Allowed types and the 10 MB cap are those of `upload_attachment`.
    The comment lists `attachments` (`id`, `filename`, `mime`, `size`, `scanState`);
    download a clean one with `download_attachment`. A failed upload or post deletes
    the drafts already uploaded.

    Args:
        body: Markdown, up to 10000 characters; empty only with at least one file.
            Write a mention as "@Display Name".
        mentions: Principal ids of the mentioned board members; they get a mail. A
            person who is not a member gives 422 `mention_not_member`.
        file_paths: Local files to attach.
    """
    return await post_message(
        f"/todos/cards/{card_id}/comments",
        {"body": body, "mentions": mentions or []},
        file_paths,
    )


def register(mcp: FastMCP) -> None:
    """Register the to-do tool group."""
    group.register(mcp)
