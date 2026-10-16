---
name: be-todos
description: To-do boards (Kanban) — gremium boards, the personal board "Meine To-Dos" and team boards behind a permission (todo_board/todo_column/todo_card and the assignee, label, checklist, comment, event and link tables). Covers the RBAC (gremium permissions todo.write/todo.configure, OAuth scope todos:write), lexorank moves with board locks, the optimistic lock (version, 409 card_version_conflict), the ETag/304 board read, link targets with per-kind read checks and "kein Zugriff" redaction, back-references (GET /api/todos/linked), agenda items from a card (agenda_item.todo_id), the ticket coupling (todo_done event, completeTodos), the mails todo_assigned/todo_mentioned/todo_due, the archive cron, the search source, privacy and the account merge. Use when working on backend/app/modules/todos, TodoService, BoardAccess, LinkResolver, worker/todos.py or the to-do parts of tickets, livevote, search, privacy or the merge.
---

# To-dos — `backend/app/modules/todos`

**Does:** Kanban boards for the work of a gremium, of one person and of a team. A card has
a title, a Markdown description, a due date, assignees, labels, a checklist, comments
with @-mentions, a timeline of events and links to an application, a meeting, an agenda
item, a ticket or another card. Every board has exactly one done column; a card in it is
done (`completed_at`).

**Key files:**
- `models.py` — `TodoBoard` (kind `gremium|personal|team`, check `ck_todo_board_owner`:
  exactly the owner column of the kind; `uq_todo_board_gremium`, `uq_todo_board_owner`;
  `archive_after_days` 1..365 or null = never, default 30), `TodoColumn`
  (`uq_todo_column_done`), `TodoCard` (`rank` collation `C`, `version`,
  `due_reminded_on`), `TodoAssignee`, `TodoLabel` (unique `lower(name)` per board),
  `TodoCardLabel`, `TodoCheckItem`, `TodoComment` (`mentions` JSONB of id strings, soft
  delete), `TodoEvent`, `TodoLink` (exactly one target column, `LINK_COLUMNS`). Constants
  `DEFAULT_COLUMNS`, `PERSONAL_BOARD_NAME`, `TEAM_BOARD_NAME`/`TEAM_BOARD_PERMISSION`.
- `access.py` — `BoardAccess` (per-request cache): `can_read` (= write), `can_configure`,
  `scope()` → `ReadScope.condition()` for the cross-board queries, `members()` (the
  assignable and mentionable people).
- `service.py` — `TodoService`: boards, columns, labels, cards, sub-resources, `mine`,
  `linked`, `search`, `card_for_agenda`, `link_agenda_item`, `complete`. Mails go to
  `outbox` (`TodoMail`); the router sends them after the commit. `mine_boards`: the rows
  under "Meine To-Dos".
- `links.py` — `LinkResolver`: `resolve` (one query per kind), `readable`, `search` (the
  link picker, `PER_KIND` 5), `card_url`.
- `lexorank.py` — `between(low, high)` (a loop, no recursion), `spread(n)`; `RankError`, `MAX_LENGTH`.
- `boards.py` — `add_default_columns`, `ensure_gremium_board` (no commit),
  `ensure_personal_board` (insert … on conflict do nothing, commits).
- `hooks.py` — `TicketTodoBridge`, the `TicketTodoHooks` of the ticket service.
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
- gremium board: read and write with `todo.write` in the gremium, configure with
  `todo.configure` (name, archive days, columns, labels); the admin bypass covers both.
- personal board: the owner only, also no admin bypass.
- team board: the holders of `board.permission` (global permission), read, write and
  configure.
- An unreadable board, card or sub-resource is 404, never 403. Configure without the
  right is 403 `todo_configure_required`. A token without `todo.write` in its scope
  (`todos:write`) gets 403 on `GET /boards`, `GET /mine` and `GET /mine/boards`, `[]` on
  the link picker and `linked`, 404 elsewhere.
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
`If-None-Match`), `GET /link-targets`, `GET /linked?kind&targetId`, `POST /cards`, `GET|PATCH
/cards/{id}` (PATCH needs `version`, 409 `card_version_conflict`), `POST
/cards/{id}/move` (`afterId`/`beforeId`, 422 `rank_neighbors_invalid`), `DELETE
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
