"""To-do board tools: boards, cards, moves and comments.

A board is readable for its members: a gremium board for the active members whose
gremium role holds `todo.write` (or an admin), the personal board for its owner only, a
team board for the holders of its permission. An unreadable board or card is 404. The
token needs the scope `todos:write`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._chat_files import post_message
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def todo_boards(gremium_id: str | None = None) -> list:
    """List the to-do boards the caller can read.

    The order is the personal board ("Meine To-Dos", created on the first call), the
    gremium boards by name, then the team boards. Each entry carries `canWrite`,
    `canConfigure` and `openCount` (cards not archived and not in the done column).

    Args:
        gremium_id: Only the board of this gremium.
    """
    return await api().get("/todos/boards", params=params(gremiumId=gremium_id))


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
    board only.
    """
    return await api().get("/todos/mine/boards")


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
