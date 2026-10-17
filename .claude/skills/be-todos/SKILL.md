---
name: be-todos
description: To-do boards (Kanban) — gremium boards, the personal board "Meine To-Dos" and team boards behind a permission (todo_board/todo_column/todo_card and the assignee, label, checklist, comment, event and link tables). Covers the RBAC (gremium permissions todo.write/todo.configure, OAuth scope todos:write), lexorank moves with board locks, the optimistic lock (version, 409 card_version_conflict), the ETag/304 board read, link targets with per-kind read checks and "kein Zugriff" redaction, back-references (GET /api/todos/linked), agenda items from a card (agenda_item.todo_id), the ticket coupling (todo_done event, completeTodos), the mails todo_assigned/todo_mentioned/todo_due, the archive cron, the live board pings (WS /api/ws/todos, GET cards/{id}/tile), the search source, privacy and the account merge. Use when working on backend/app/modules/todos, TodoService, BoardAccess, LinkResolver, worker/todos.py or the to-do parts of tickets, livevote, search, privacy or the merge.
---

# To-dos — `backend/app/modules/todos`

**Does:** Kanban boards for the work of a gremium, of one person and of a team. A card has
a title, a Markdown description, a due date, assignees, labels, a checklist, comments
with @-mentions, a timeline of events and links to an application, a meeting, an agenda
item, a vote, a gremium, an invoice, a booking, a ticket or another card. Every board has exactly one done column; a card in it is
done (`completed_at`).

**Key files:**
- `models.py` — `TodoBoard` (kind `gremium|personal|team`, check `ck_todo_board_owner`:
  exactly the owner column of the kind; `uq_todo_board_gremium`, `uq_todo_board_owner`;
  `archive_after_days` 1..365 or null = never, default 30), `TodoColumn`
  (`uq_todo_column_done`), `TodoCard` (`rank` collation `C`, `version`,
  `due_reminded_on`), `TodoAssignee`, `TodoLabel` (unique `lower(name)` per board),
  `TodoCardLabel`, `TodoCheckItem`, `TodoComment` (`mentions` JSONB of id strings, soft
  delete), `TodoEvent`, `TodoLink` (exactly one target column, `LINK_COLUMNS`; every
  target FK is `ON DELETE CASCADE`; `ck_todo_link_one_target` counts the columns of
  `LINK_COLUMNS`, partial indexes `uq_todo_link_<column>` and `ix_todo_link_<column>`).
  `LINK_KINDS` is also the picker order: application, meeting, agenda_item, vote,
  gremium, invoice, expense (`budget_expense`), ticket, todo. Migration `527854b79d68`
  adds `vote_id`, `gremium_id`, `invoice_id`, `expense_id`. Constants
  `DEFAULT_COLUMNS`, `PERSONAL_BOARD_NAME`, `TEAM_BOARD_NAME`/`TEAM_BOARD_PERMISSION`.
- `access.py` — `BoardAccess` (per-request cache): `can_read` (write or `todo.read_all`),
  `can_write`, `can_configure`, `scope()` → `ReadScope.condition()` for the cross-board
  queries (`all_gremien`, `all_teams` for the global keys), `members()` (the assignable
  and mentionable people); `token_reads` (the token gate), `TODO_ALL`, `TODO_READ_ALL`.
- `service.py` — `TodoService`: boards, columns, labels, cards, sub-resources, `mine`,
  `linked`, `search`, `card_for_agenda`, `link_agenda_item`, `complete`. Mails go to
  `outbox` (`TodoMail`); the router sends them after the commit. `mine_boards`: the rows
  under "Meine To-Dos"; `all_boards`: the meta-board "Alle"; both through
  `_board_rows(mine=...)`.
- `links.py` — `LinkResolver`: `resolve` (one query per kind), `readable`, `search` (the
  link picker, `PER_KIND` 5), `card_url`. The read rule of each kind is the gate of its
  own module, so a link never shows more than that module's page:
  application `resolve_app_read` (confirmed only); meeting and agenda item
  `meeting_read_scope`; vote `voting.listing.read_scope` (the SQL form of
  `assert_can_read`); gremium `admin.gremium_roles.gremium_view_scope` (the tab
  "Gremien": `gremium.view_all` or an active membership, cached per resolver); invoice and
  expense `budget.access.has_budget_read` (`budget.view`/`.structure`/`.book`, the gate
  of `GET /invoices` and `/expenses`); ticket `ticket.manage`; todo the board rule.
  Titles and urls: vote = question, else the application title when the viewer can read that application (`/voting/{id}`, detail
  `meetingTitle`, `date`, `voteStatus`, `voteResult`); gremium = name (`/gremien/{id}`);
  invoice = number, else supplier (`/invoices?id={id}`, detail `number`,
  `counterparty`, `amount`, `date` = issue date, `invoiceStatus`); expense = description
  (`/expenses?id={id}`, a sub-booking links its parent row; detail `amount`,
  `bookingKind`, `costCentre` = path key, `counterparty`, `date`). Picker candidates
  reuse the module lists: `list_votes` (every status, drafts too), the trigram match of
  the search source on gremium name/slug inside the Gremien scope,
  `list_invoices_paged`, `list_expenses_paged` (top-level bookings only).
- `lexorank.py` — `between(low, high)` (a loop, no recursion), `spread(n)`; `RankError`, `MAX_LENGTH`.
- `boards.py` — `add_default_columns`, `ensure_gremium_board` (no commit),
  `ensure_personal_board` (insert … on conflict do nothing, commits).
- `hooks.py` — `TicketTodoBridge`, the `TicketTodoHooks` of the ticket service.
- `live.py` — the board pings: `board_channel(id)` → `todo-board:{id}`, `CHANNEL_PATTERN`,
  `BoardPings` (the collector of one request), `publish_pings`, `todo_broker(app.state)`.
- `socket.py` — `WS /api/ws/todos` (`ws_router`, `TodoLiveConnection`).
- `privacy.py` — `erase_todos` (locks the personal board, then its cards `FOR UPDATE`, before
  it reads the comment ids, like the Gremium delete; drops the comment-file rows with
  `drop_for_messages` and returns the storage keys, which the caller removes after its
  commit), `todo_export`. `add_comment` locks the
  board and then the card (`_card(..., lock=True)`) before the insert, else it deadlocks with
  those two. `merge.py` — `fold_personal_board`,
  `rewrite_mentions`.
- Outside the module: `notifications/todos.py` (three mails), `worker/todos.py`
  (`archive_done_todos`, `process_todo_due`), `livevote/agenda_service.add_todo_in_tx`,
  `search/service._todos`, `admin/service/gremien.create_gremium` (board with the
  gremium), `admin/principal_merge._todos`, `shared/people.permission_holders`.

**Rights:**
- gremium board: write with `todo.write` in the gremium, configure with
  `todo.configure` (name, archive days, columns, labels); the admin bypass covers both.
- personal board: the owner only, also no admin bypass and no global key.
- team board: the holders of `board.permission` (global permission), read, write and
  configure.
- Global keys (`PERMISSION_CATALOGUE`, migration `199cc9a409f2` grants both to the role
  `admin`): `todo.all` writes the cards of every gremium and team board, `todo.read_all`
  only reads them. Neither reaches a personal board, neither configures
  (`can_configure` asks the native right only), and neither makes a member:
  `members()`/`member_ids` stay as they are, so a holder is not assignable, not
  mentionable and gets no `todo_due`. Read = write or `todo.read_all`. Through a
  global key a team board also needs its own permission in the token scope
  (`global_reach`: `scope_allows(board.permission)`), in `can_read`, `can_write` and
  `ReadScope` (a token then gets `team_permissions`, not `all_teams`), because the team
  permission guards the board. A cookie session lets everything through, so only a
  narrow token changes: an admin `read` token does not see the team board "Plattform"
  (`ticket.manage`, 404, not listed).
- An unreadable board, card or sub-resource is 404, never 403. A card write on a board
  that the caller reads but cannot write is 403 `todo_write_required` (`_card(...,
  write=True)` / `_board(..., write=True)`, after the read check): create, patch, move,
  transfer (both boards), archive/restore, assignees, card labels, checklist, links,
  comments (create, edit, delete, files), `card_for_agenda`; `completeTodos` moves only
  the cards that the actor writes. Configure without the right is 403
  `todo_configure_required`. `canWrite` of `TodoBoardSummary`, `TodoBoardOut`,
  `TodoCardDetail` and `TodoAssignedBoard` is `can_write`.
- Token scope: the native rights need `todo.write` in the scope (`todos:write`);
  `todo.all` (`todos:write`) and `todo.read_all` (`read`) go through `Principal.has`. A
  token whose scope holds none of `todo.write`, `todo.all`, `todo.read_all`
  (`token_reads`) gets 403 on `GET /boards`, `GET /mine` and `GET /mine/boards`, `[]` on
  the link picker, `linked` and the search, 404 elsewhere. A `read` token of an admin
  reads every gremium board and the team boards whose permission is in its scope,
  and writes none.
- Defaults: the migration grants `todo.write` to every gremium role and `todo.configure`
  to `vorstand` and `manager`; the forced `member` role of a new gremium has
  `vote.cast` and `todo.write`.
- Assignees and mentions must be members (422 `assignee_not_allowed`,
  `mention_not_member`): active gremium members whose role holds `todo.write`, the owner,
  or the permission holders.

**API surface** (`/api/todos`): `GET /boards` (first call creates the personal board;
order personal, gremium by name, team), `GET|PATCH /boards/{id}` (GET has a weak ETag over
the whole body, 304 on `If-None-Match`), `GET /boards/{id}/members`, `GET
/boards/{id}/archive`, `POST /boards/{id}/columns`, `PUT /boards/{id}/columns/order`,
`PATCH|DELETE /boards/{id}/columns/{cid}` (`isDone: true` moves the done flag; delete: 409
`done_column_required` / `column_not_empty` without `moveTo`), labels (409
`label_exists`), `GET /mine` (`dueSoonCount`: due within 7 days, Berlin, overdue
included), `GET /mine/boards` (`TodoAssignedBoard[]`: every readable board except the
personal one that holds live cards assigned to the caller, done ones too; each with all
its columns in order, `cardCount` = the caller's cards there, its labels and only the
caller's cards; gremium boards by name, then team; the read scope keeps out a board the
caller cannot read even when a card still names them; one query for the cards, one each
for columns, labels and the tile facts; weak ETag over the list, 304 on
`If-None-Match`), `GET /all/boards` (`TodoAssignedBoard[]`, the meta-board "Alle":
every readable board through the read scope, so a `todo.read_all` holder gets the shared
boards with `canWrite: false`; the personal board first (the call creates it, like `GET
/boards`), then gremium boards by name, then team; each with all its columns, its labels
and every live card, done ones too; `cardCount` = the live cards of the column; the same
token gate (403), the same weak ETag and 304, and a constant number of queries: one for
the boards, one for the cards, one each for columns and labels, and the tile facts),
`GET /link-targets` (`kind` = `all` or a `TodoLinkKind`), `GET /linked?kind&targetId`
(`TodoLinkedKind`: every kind but `todo`), `POST /cards`, `GET|PATCH
/cards/{id}` (PATCH needs `version`, 409 `card_version_conflict`), `POST
/cards/{id}/move` (`afterId`/`beforeId`, 422 `rank_neighbors_invalid`), `POST
/cards/{id}/transfer` (`CardTransfer`: `boardId`, `columnId?` = default the first column,
`beforeId?`/`afterId?` as in the move = default the end, 422 `rank_neighbors_invalid` for
a neighbor outside the target column;
answers `TodoCardDetail`; 404 for a target board that the caller cannot read, 403
`todo_write_required` / `transfer_to_personal`, 422 `transfer_same_board` /
`column_not_on_board`, 409 `card_moved` / `card_archived`), `DELETE
/cards/{id}` (archive), `POST /cards/{id}/restore`, assignees, labels, checklist, links
(422 `link_self`, `link_target_not_found`; 409 `link_exists`), comments (403
`not_comment_author`). `POST /cards/{id}/comments` takes `CommentCreate` (`body`,
`mentions`, `attachmentIds` ≤ 5, `draftToken`); the files bind with `todo_comment_id`,
`TodoCommentOut.attachments` lists them, and a reader of the board downloads them through
`/api/attachments/{id}/download` (be-files); the delete of a comment removes its files.

**Data rules:**
- Create, move, `complete`, the done-flag move and column delete lock the board row; move
  and `complete` read the card again after the lock (`refresh`); a move writes one row unless two
  ranks collide (`RankError` → `spread` over the column). Create, move, `complete` and
  column delete also re-rank the live cards of the column with `spread` when the new rank
  is longer than `MAX_LENGTH` (50): every append adds about one digit per six cards, and
  the done column never empties (`_append`, `_rank` in `service.py`). Every write bumps
  `todo_board.updated_at`, so the ETag changes.
- `transfer` moves a card into a column of another board: between `afterId` and
  `beforeId` (`_slot` and `_place`, the same code as the move), else to the end. It locks both boards in
  id order, because two transfers between the same two boards in opposite directions
  deadlock in the other order, and then reads the card again (`refresh`): a card that a
  parallel transfer moved gives 409 `card_moved`. Labels are per board, so a label stays
  only when the target has one with the same `lower(name)`, and the others drop. The
  transfer never creates a label, because that needs `todo.configure`. Assignees who are
  not members of the target (`member_ids`) drop, without a mail. Entry into the target
  done column sets `completed_at` and writes `todo_done` only for a card that was not
  done; a done card keeps its `completed_at`; another column clears it. One `moved` event
  carries the column keys plus `fromBoardId`/`fromBoardName`/`toBoardId`/`toBoardName`,
  `droppedLabels` (names) and `droppedAssignees` (count). `version` does not change.
  Links, comments with their files, the checklist and the events stay with the card, so
  the comment files then download under the read rule of the target board.
- A transfer from a shared board (gremium, team) into a personal board is 403
  `transfer_to_personal` (`_check_transfer_kinds`, one check), because the comments,
  files and links of the card would then leave the reach of everyone else on the
  board. Personal → shared and shared → shared stay.
- A card of the actor's own personal board without assignees takes the actor as
  assignee when the actor is a member of the target (`member_ids`; an `assigned` event,
  no mail), because the card would else leave "Meine To-Dos" at once.
- A write that waited for the board lock while a transfer moved the card away is 409
  `card_moved`: `move` and `_card(lock=True)` compare `card.board_id` after the lock
  (the lock held is the old board's), and `complete` returns False. Every card write
  (patch, archive, restore, assignees, labels, checklist, links, comments) loads the card
  with `_card(lock=True, write=True)`, so the check covers it and its ping goes to the
  board the card is on. A move or a
  transfer whose `_place` respreads the column pings the whole board (`board`),
  because every card of the column got a new rank.
- `patch_column` and `delete_column` take the board lock before they read the column
  (`_column` reads with `populate_existing`), so `is_done` is the committed value and a
  parallel done-flag move cannot leave the board without a done column.
- Lock order is board, then card, everywhere: `patch` (`_card(lock=True)`) locks the board
  before the card, and the archive cron locks the boards of the due cards (by id) before
  the cards. The other order deadlocks with a move (`test_todos_locks.py`). The card lock
  is `FOR NO KEY UPDATE`, because `FOR UPDATE` conflicts with the `FOR KEY SHARE` of the
  `todo_link.todo_id` foreign key check, and two cards on two boards that link each other
  at the same time then deadlock.
- The board also comes before a meeting: `card_for_agenda` locks the board and the card
  before `add_todo_in_tx` locks the meeting, because a card create locks the board and
  then inserts a meeting link (a key share on the meeting row). `TicketTodoBridge.complete`
  takes the boards in id order, so two `completeTodos` closes on the same boards wait
  instead of deadlocking.
- A write that changes a card sets `card.updated_at` itself. The column has
  `onupdate=now()`: without the explicit value SQLAlchemy expires the attribute and the
  response after the commit loads it outside the greenlet (`MissingGreenlet`).
- `version` guards title, description and due date only; moves and sub-resources do not
  bump it. A `moved` event is written only on a column change.
- Entry into the done column sets `completed_at` and writes `todo_done` (payload
  `cardId`, `cardTitle`, `boardId`) into every linked ticket; leaving it clears
  `completed_at`. The same holds for the column paths: `PATCH` with `isDone` and
  `DELETE …?moveTo=<done>` (which also writes a `moved` event per card); both change
  archived cards too, but an archived card gets only `completed_at`, never a `todo_done`
  (it was not finished). A restore into the done column sets a new `completed_at`, so the
  archive cron does not archive the card again at once. The ticket detail shows `cardTitle` only to a reader of the board.
- A link target that the viewer cannot read has `accessible: false` and no title, url or
  detail (the frontend shows "kein Zugriff"). Event payloads of `linked`/`unlinked` get
  the title the same way.

**Coupling:** ticket PATCH `completeTodos` moves the open linked cards that the actor can
write into done (`TicketTodoBridge.complete`). `POST /meetings/{id}/agenda` with `todoId`
checks the card (404, 422 `todo_archived` / `todo_wrong_board`: only a card of the board of
the meeting gremium), adds an item with the card title (409 `todo_already_on_agenda`) and
links the card to the item.

**Live (board pings):** the client reads only what changed, through REST, so every
read rule stays in force (a tile is per viewer, `primaryLink` is redacted).
- Messages on `todo-board:{board_id}`: `{"type":"card","boardId","cardId"}` (a card of the
  board was created or changed: any field, a sub-resource, a comment, a move inside the
  board, a restore), `{"type":"card_removed",…}` (the card left the board: archived or
  transferred away), `{"type":"board","boardId"}` (name, settings, columns, labels, or more
  than one card of the board in one request). A transfer sends `card_removed` on the source
  and `card` on the target.
- Collector: `TodoService._touch(board, card=None, *, removed=False)` runs at every board
  write and records the ping in `service.pings` (`BoardPings`). A card that left stays
  `card_removed` in the same request.
- Publish after the commit: `router.get_live_todo_service` wraps `get_todo_service`, and its
  exit runs after the response (the commit of `get_session` runs first), so a refused
  write sends nothing. `publish_pings` logs and swallows a broker fault. The ticket coupling
  (`TicketTodoBridge.complete`, `broker=`) and the agenda add with `todoId`
  (`livevote/router.add_agenda_item`) publish after their own commit. The archive cron sends
  no pings (the poll covers it).
- `GET /api/todos/cards/{id}/tile` → `TodoCardTile` (the tile of the board read, for this
  viewer). 404 when unreadable or archived.
- Socket `WS /api/ws/todos`: the session cookie only (`app.shared.ws.resolve_ws_principal`,
  Origin check; 4401 without a session, 4403 for a foreign origin). Client frame
  `{"type":"subscribe","boardIds":[…]}` replaces the set (at most `MAX_BOARDS` = 100, more
  gives the error `too_many_boards`). Every subscribe resolves the principal again from
  the session cookie of the handshake (`get_todo_ws_resolver` → `resolve_ws_principal`),
  so a lost role or membership counts at once; a session that is gone closes with 4401.
  The server keeps the ids that `BoardAccess.can_read` allows, drops the rest silently
  and answers `{"type":"subscribed","boardIds":[…]}`. A socket that only listens is
  checked too: before the pump forwards a ping, a last check older than
  `RECHECK_SECONDS` (300) resolves the principal and filters the set with `can_read`
  again (4401 when the session is gone, a lost board drops out silently). An
  `asyncio.Lock` serializes the checks of the subscribe and the pump, because both use
  the one session of the socket. The clock is injectable (`clock=`) for the tests. It
  rolls back after each check, so the socket holds no transaction. One `PSUBSCRIBE todo-board:*` per socket
  (`PatternBroker.subscribe_pattern`), filtered by the subscribed ids. Limits: 5 sockets per
  principal (error `too_many_connections`, close 4403; per process, like the meeting
  socket), a token bucket of 5 frames/s (burst 10, `rate_limited`). Bad frames (binary,
  not JSON, a bad shape) get `invalid_message` / `unknown_type`, count against the
  throttle and keep the socket. No heartbeat of its own (uvicorn's
  WebSocket pings, like the meeting socket).
- Tests: `tests/unit/modules/todos/test_live.py`, `tests/integration/modules/todos/test_todos_live.py`
  (override `get_todo_broker` and `get_todo_ws_broker` with one `InMemoryBroker`).

**Mails:** `todo_assigned` (new assignee except the actor), `todo_mentioned` (new mentions
except the author, with an excerpt), both after the commit and best effort; `todo_due` from
the deadline cron to the assignees of an open card due tomorrow (Berlin) who are still
members of the board (`BoardAccess.member_ids`), from 07:00 Berlin,
once per card and due date (`due_reminded_on`, idempotency key `todo_due:<card>:<date>`).
All three are opt-out kinds. The idempotency key of `todo_assigned` and `todo_mentioned`
carries `TodoMail.event_id` (new per mail), because the key is the arq job id and a repeated
assignment or an identical mention would otherwise be dropped.

**Crons:** `archive_done_todos` 03:50: done cards whose `completed_at` is older than the
board's `archive_after_days`, event `archived` without actor.

**Privacy and merge:** the erasure deletes the comment files of the personal board (rows,
objects, audit), the assignments and the personal board; cards,
comments and events on shared boards keep the id and show "Gelöschte Person". The Art. 15
export has the sheets "To-Dos" and "To-Do-Kommentare" (with the file names in "Anhänge"). The merge (area `todos`) rewrites
creator, author, actor, link creator and the mentions, combines assignments, and moves the
personal board or folds it into the target's board.

**Gotchas:**
- Select-then-insert writes (`add_assignee`, `add_card_label`, `add_link`, `add_label`) take
  the board lock first, so a parallel identical request waits and then sees the row
  (no-op or 409) instead of a unique violation (500).
- The migration `59ccfd0a0856_todos` is idempotent and backfills a board per gremium and
  the team board "Plattform" (`ticket.manage`). Integration tests truncate `principal`
  CASCADE, which empties every todo table: a test creates its own boards.
- Unit tests use `tests/unit/modules/todos/fakes.py` (`ScriptedSession`, `FakeAccess`,
  `FakeLinks`); `conftest.py` stubs `person_refs`.

**Related:** be-tickets, be-livevote, be-notifications, be-search, be-privacy, be-admin,
be-auth, frontend
