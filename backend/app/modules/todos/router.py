"""To-dos API router (``/todos``).

Every route needs a principal session (401). An OAuth token reads to-dos when its
scope lets ``todo.write`` or ``todo.all`` (``todos:write``) or ``todo.read_all``
(``read``) through: without one of them ``GET /todos/boards``, ``GET /todos/mine``
and ``GET /todos/mine/boards`` answer 403, the link picker and ``linked`` ``[]``,
and every board or card 404. A write needs ``todo.write`` or ``todo.all`` in the
scope. A board or card that the caller cannot read answers 404, never 403; a card
write on a board that the caller reads but cannot write 403
``todo_write_required``; a configuration change without ``todo.configure`` 403
``todo_configure_required``.

``GET /todos/boards/{id}`` and ``GET /todos/mine/boards`` carry a weak ``ETag`` over
their body and answer 304 to a matching ``If-None-Match``; the frontend polls them
every 30 s. Mails of a write (``todo_assigned``, ``todo_mentioned``) go out as a
background task after the commit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response, status

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.files.service import FilesService
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.todos import notify_todo_mails
from app.modules.todos.access import token_reads
from app.modules.todos.schemas import (
    AssigneeIn,
    BoardPatch,
    CardCreate,
    CardLabelIn,
    CardMove,
    CardPatch,
    CardTransfer,
    CheckItemCreate,
    CheckItemPatch,
    ColumnCreate,
    ColumnOrder,
    ColumnPatch,
    CommentCreate,
    CommentIn,
    LabelCreate,
    LabelPatch,
    LinkIn,
    TodoAssignedBoard,
    TodoBoardOut,
    TodoBoardSummary,
    TodoCardDetail,
    TodoCardTile,
    TodoCommentOut,
    TodoLabelOut,
    TodoLinkedCard,
    TodoLinkKind,
    TodoLinkTarget,
    TodoMember,
    TodoMine,
)
from app.modules.todos.service import TodoMail, TodoService
from app.settings import Settings
from app.shared.errors import ProblemDetail
from app.shared.paging import Page, PageParams

router = APIRouter(prefix="/todos", tags=["todos"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


Member = Annotated[Principal, Depends(require_principal())]


def get_todo_service(session: DbSession, request: Request) -> TodoService:
    """Wire the service with the object storage (a test overrides it).

    The storage removes the objects of the files of a deleted comment.
    """
    storage = getattr(request.app.state, "object_storage", None)
    return TodoService(session, files=FilesService(session, storage=storage))


ServiceDep = Annotated[TodoService, Depends(get_todo_service)]

#: Sends the mails of a write after the commit (background task).
TodoMailSender = Callable[[Settings, Sequence[TodoMail], object], Awaitable[None]]


async def _deliver_todo_mails(settings: Settings, mails: Sequence[TodoMail], pool: object) -> None:
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    await notify_todo_mails(queue=queue, settings=settings, mails=mails)


def get_todo_mail_sender() -> TodoMailSender:
    """Return the injectable mail sender that a test can override."""
    return _deliver_todo_mails


MailSenderDep = Annotated[TodoMailSender, Depends(get_todo_mail_sender)]


def _send(
    service: TodoService,
    background: BackgroundTasks,
    request: Request,
    settings: Settings,
    send: TodoMailSender,
) -> None:
    if service.outbox:
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send, settings, list(service.outbox), pool)


def _weak_etag(body: object) -> str:
    text = json.dumps(body, sort_keys=True)
    return f'W/"{hashlib.sha256(text.encode()).hexdigest()[:32]}"'


def board_etag(board: TodoBoardOut) -> str:
    """The weak ETag of a board read: a hash over its whole body for this viewer."""
    return _weak_etag(board.model_dump(by_alias=True, mode="json"))


def mine_boards_etag(boards: Sequence[TodoAssignedBoard]) -> str:
    """The weak ETag of ``GET /todos/mine/boards``: a hash over the whole list."""
    return _weak_etag([b.model_dump(by_alias=True, mode="json") for b in boards])


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    wanted = etag.removeprefix("W/")
    return any(
        tag.strip() == "*" or tag.strip().removeprefix("W/") == wanted for tag in header.split(",")
    )


# -- boards ---------------------------------------------------------------------


@router.get("/boards", response_model=list[TodoBoardSummary], responses=_errors(401, 403))
async def list_boards(
    service: ServiceDep,
    principal: Member,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
) -> list[TodoBoardSummary]:
    """List the readable boards: personal, the gremium boards by name, then team.

    The first call creates the personal board "Meine To-Dos".
    """
    return await service.list_boards(principal, gremium_id=gremium_id)


@router.get(
    "/boards/{board_id}",
    response_model=TodoBoardOut,
    responses={**_errors(401, 404), 304: {"description": "Not modified"}},
)
async def get_board(
    board_id: UUID,
    service: ServiceDep,
    principal: Member,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> TodoBoardOut | Response:
    """Return a board: columns, labels and the tiles of its live cards (ETag, 304)."""
    board = await service.board(board_id, principal)
    etag = board_etag(board)
    if _matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return board


@router.patch(
    "/boards/{board_id}", response_model=TodoBoardOut, responses=_errors(401, 403, 404, 422)
)
async def patch_board(
    board_id: UUID, payload: BoardPatch, service: ServiceDep, principal: Member
) -> TodoBoardOut:
    """Rename the board or change ``archiveAfterDays`` (todo.configure)."""
    return await service.patch_board(board_id, payload, principal)


@router.get(
    "/boards/{board_id}/members", response_model=list[TodoMember], responses=_errors(401, 404)
)
async def board_members(board_id: UUID, service: ServiceDep, principal: Member) -> list[TodoMember]:
    """The assignable people of the board (also the list of the @-mentions)."""
    return await service.members(board_id, principal)


@router.get(
    "/boards/{board_id}/archive",
    response_model=Page[TodoCardTile],
    responses=_errors(401, 404, 422),
)
async def board_archive(
    board_id: UUID,
    service: ServiceDep,
    principal: Member,
    page: Annotated[PageParams, Depends()],
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[TodoCardTile]:
    """The archived cards of the board, newest archive first."""
    return await service.archive(board_id, principal, q=q, limit=page.limit, offset=page.offset)


@router.post(
    "/boards/{board_id}/columns",
    response_model=TodoBoardOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def add_column(
    board_id: UUID, payload: ColumnCreate, service: ServiceDep, principal: Member
) -> TodoBoardOut:
    """Append a column (todo.configure)."""
    return await service.add_column(board_id, payload.name, principal)


@router.put(
    "/boards/{board_id}/columns/order",
    response_model=TodoBoardOut,
    responses=_errors(401, 403, 404, 422),
)
async def order_columns(
    board_id: UUID, payload: ColumnOrder, service: ServiceDep, principal: Member
) -> TodoBoardOut:
    """Order the columns; the list names every column once (todo.configure)."""
    return await service.order_columns(board_id, payload.column_ids, principal)


@router.patch(
    "/boards/{board_id}/columns/{column_id}",
    response_model=TodoBoardOut,
    responses=_errors(401, 403, 404, 422),
)
async def patch_column(
    board_id: UUID,
    column_id: UUID,
    payload: ColumnPatch,
    service: ServiceDep,
    principal: Member,
) -> TodoBoardOut:
    """Rename a column or make it the done column (todo.configure)."""
    return await service.patch_column(board_id, column_id, payload, principal)


@router.delete(
    "/boards/{board_id}/columns/{column_id}",
    response_model=TodoBoardOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def delete_column(
    board_id: UUID,
    column_id: UUID,
    service: ServiceDep,
    principal: Member,
    move_to: Annotated[UUID | None, Query(alias="moveTo")] = None,
) -> TodoBoardOut:
    """Delete a column; ``moveTo`` takes its cards (409 ``column_not_empty`` without)."""
    return await service.delete_column(board_id, column_id, principal, move_to=move_to)


@router.post(
    "/boards/{board_id}/labels",
    response_model=TodoLabelOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 409, 422),
)
async def add_label(
    board_id: UUID, payload: LabelCreate, service: ServiceDep, principal: Member
) -> TodoLabelOut:
    """Add a label (todo.configure); a taken name gives 409 ``label_exists``."""
    return await service.add_label(board_id, payload, principal)


@router.patch(
    "/boards/{board_id}/labels/{label_id}",
    response_model=TodoLabelOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def patch_label(
    board_id: UUID,
    label_id: UUID,
    payload: LabelPatch,
    service: ServiceDep,
    principal: Member,
) -> TodoLabelOut:
    """Rename a label or change its color (todo.configure)."""
    return await service.patch_label(board_id, label_id, payload, principal)


@router.delete(
    "/boards/{board_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def delete_label(
    board_id: UUID, label_id: UUID, service: ServiceDep, principal: Member
) -> Response:
    """Delete a label (todo.configure)."""
    await service.delete_label(board_id, label_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- across boards ------------------------------------------------------------------


@router.get("/mine", response_model=TodoMine, responses=_errors(401, 403))
async def mine(service: ServiceDep, principal: Member) -> TodoMine:
    """The open cards assigned to the caller, with the count due within 7 days."""
    return await service.mine(principal)


@router.get(
    "/mine/boards",
    response_model=list[TodoAssignedBoard],
    responses={**_errors(401, 403), 304: {"description": "Not modified"}},
)
async def mine_boards(
    service: ServiceDep,
    principal: Member,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> list[TodoAssignedBoard] | Response:
    """The readable shared boards with the live cards assigned to the caller (ETag, 304).

    Each board brings all its columns and labels but only the caller's cards, done
    ones included; the personal board and a board without such a card are left out.
    """
    boards = await service.mine_boards(principal)
    etag = mine_boards_etag(boards)
    if _matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return boards


@router.get("/link-targets", response_model=list[TodoLinkTarget], responses=_errors(401, 422))
async def link_targets(
    service: ServiceDep,
    principal: Member,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    kind: Literal["all", "application", "meeting", "agenda_item", "ticket", "todo"] = "all",
    exclude_card_id: Annotated[UUID | None, Query(alias="excludeCardId")] = None,
) -> list[TodoLinkTarget]:
    """Search the link targets that the caller may read (at most 5 per kind)."""
    if not token_reads(principal):
        return []
    return await service.links.search(q, kind, principal, exclude_card_id=exclude_card_id)


@router.get("/linked", response_model=list[TodoLinkedCard], responses=_errors(401, 422))
async def linked(
    service: ServiceDep,
    principal: Member,
    kind: Literal["application", "meeting", "agenda_item", "ticket"],
    target_id: Annotated[UUID, Query(alias="targetId")],
) -> list[TodoLinkedCard]:
    """The readable live cards that link to the target (back-references)."""
    return await service.linked(kind, target_id, principal)


# -- cards ------------------------------------------------------------------------


@router.post(
    "/cards",
    response_model=TodoCardDetail,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def create_card(
    payload: CardCreate,
    service: ServiceDep,
    principal: Member,
    background: BackgroundTasks,
    request: Request,
    settings: SettingsDep,
    send: MailSenderDep,
) -> TodoCardDetail:
    """Create a card at the end of its column (default: the first column)."""
    out = await service.create(payload, principal)
    _send(service, background, request, settings, send)
    return out


@router.get("/cards/{card_id}", response_model=TodoCardDetail, responses=_errors(401, 404))
async def get_card(card_id: UUID, service: ServiceDep, principal: Member) -> TodoCardDetail:
    """The whole card with links, checklist, events and comments (archived too)."""
    return await service.card(card_id, principal)


@router.patch(
    "/cards/{card_id}", response_model=TodoCardDetail, responses=_errors(401, 403, 404, 409, 422)
)
async def patch_card(
    card_id: UUID, payload: CardPatch, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Change title, description or due date; a stale ``version`` gives 409."""
    return await service.patch(card_id, payload, principal)


@router.post(
    "/cards/{card_id}/move", response_model=TodoCardTile, responses=_errors(401, 403, 404, 422)
)
async def move_card(
    card_id: UUID, payload: CardMove, service: ServiceDep, principal: Member
) -> TodoCardTile:
    """Move a card between ``afterId`` and ``beforeId`` of a column (default: the end)."""
    return await service.move(card_id, payload, principal)


@router.post(
    "/cards/{card_id}/transfer",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404, 409, 422),
)
async def transfer_card(
    card_id: UUID, payload: CardTransfer, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Move a card to another board; labels by name and assignees by membership stay."""
    return await service.transfer(card_id, payload, principal)


@router.delete(
    "/cards/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def archive_card(card_id: UUID, service: ServiceDep, principal: Member) -> Response:
    """Archive a card."""
    await service.archive_card(card_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/cards/{card_id}/restore", response_model=TodoCardDetail, responses=_errors(401, 403, 404)
)
async def restore_card(card_id: UUID, service: ServiceDep, principal: Member) -> TodoCardDetail:
    """Bring an archived card back."""
    return await service.restore_card(card_id, principal)


@router.post(
    "/cards/{card_id}/assignees",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404, 422),
)
async def add_assignee(
    card_id: UUID,
    payload: AssigneeIn,
    service: ServiceDep,
    principal: Member,
    background: BackgroundTasks,
    request: Request,
    settings: SettingsDep,
    send: MailSenderDep,
) -> TodoCardDetail:
    """Assign a member of the board (422 ``assignee_not_allowed`` otherwise)."""
    out = await service.add_assignee(card_id, payload.principal_id, principal)
    _send(service, background, request, settings, send)
    return out


@router.delete(
    "/cards/{card_id}/assignees/{principal_id}",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404),
)
async def remove_assignee(
    card_id: UUID, principal_id: UUID, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Remove an assignee."""
    return await service.remove_assignee(card_id, principal_id, principal)


@router.post(
    "/cards/{card_id}/labels", response_model=TodoCardDetail, responses=_errors(401, 403, 404, 422)
)
async def add_card_label(
    card_id: UUID, payload: CardLabelIn, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Put a label of the board on the card."""
    return await service.add_card_label(card_id, payload.label_id, principal)


@router.delete(
    "/cards/{card_id}/labels/{label_id}",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404),
)
async def remove_card_label(
    card_id: UUID, label_id: UUID, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Take a label off the card."""
    return await service.remove_card_label(card_id, label_id, principal)


@router.post(
    "/cards/{card_id}/checklist",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404, 422),
)
async def add_check_item(
    card_id: UUID, payload: CheckItemCreate, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Append a checklist item."""
    return await service.add_check_item(card_id, payload.text, principal)


@router.patch(
    "/cards/{card_id}/checklist/{item_id}",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404, 422),
)
async def patch_check_item(
    card_id: UUID,
    item_id: UUID,
    payload: CheckItemPatch,
    service: ServiceDep,
    principal: Member,
) -> TodoCardDetail:
    """Rename, tick or move a checklist item."""
    return await service.patch_check_item(card_id, item_id, payload, principal)


@router.delete(
    "/cards/{card_id}/checklist/{item_id}",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404),
)
async def delete_check_item(
    card_id: UUID, item_id: UUID, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Delete a checklist item."""
    return await service.delete_check_item(card_id, item_id, principal)


@router.post(
    "/cards/{card_id}/links",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404, 409, 422),
)
async def add_link(
    card_id: UUID, payload: LinkIn, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Link the card to a target that the caller reads."""
    kind: TodoLinkKind = payload.kind
    return await service.add_link(card_id, kind, payload.target_id, principal)


@router.delete(
    "/cards/{card_id}/links/{link_id}",
    response_model=TodoCardDetail,
    responses=_errors(401, 403, 404),
)
async def remove_link(
    card_id: UUID, link_id: UUID, service: ServiceDep, principal: Member
) -> TodoCardDetail:
    """Remove a link of the card."""
    return await service.remove_link(card_id, link_id, principal)


@router.post(
    "/cards/{card_id}/comments",
    response_model=TodoCommentOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def add_comment(
    card_id: UUID,
    payload: CommentCreate,
    service: ServiceDep,
    principal: Member,
    background: BackgroundTasks,
    request: Request,
    settings: SettingsDep,
    send: MailSenderDep,
) -> TodoCommentOut:
    """Comment on a card; the new mentions get the mail ``todo_mentioned``.

    ``attachmentIds`` and ``draftToken`` bind the files of the comment; a draft that
    is missing, expired, foreign or infected gives 422 ``draft_attachments_missing``.
    """
    out = await service.add_comment(
        card_id,
        payload.body,
        payload.mentions,
        principal,
        attachment_ids=payload.attachment_ids,
        draft_token=payload.draft_token,
        pepper=settings.magic_link_secret,
    )
    _send(service, background, request, settings, send)
    return out


@router.patch(
    "/cards/{card_id}/comments/{comment_id}",
    response_model=TodoCommentOut,
    responses=_errors(401, 403, 404, 422),
)
async def edit_comment(
    card_id: UUID,
    comment_id: UUID,
    payload: CommentIn,
    service: ServiceDep,
    principal: Member,
    background: BackgroundTasks,
    request: Request,
    settings: SettingsDep,
    send: MailSenderDep,
) -> TodoCommentOut:
    """Change an own comment (403 ``not_comment_author`` otherwise)."""
    out = await service.edit_comment(card_id, comment_id, payload.body, payload.mentions, principal)
    _send(service, background, request, settings, send)
    return out


@router.delete(
    "/cards/{card_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404),
)
async def delete_comment(
    card_id: UUID, comment_id: UUID, service: ServiceDep, principal: Member
) -> Response:
    """Delete an own comment and its files (403 ``not_comment_author`` otherwise)."""
    await service.delete_comment(card_id, comment_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
