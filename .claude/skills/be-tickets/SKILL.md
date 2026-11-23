---
name: be-tickets
description: Tickets from the help menu — problem reports, questions and ideas (ticket/ticket_note/ticket_event, number T-7K3QX9MD: eight random characters, numbers.py). Covers the public one-way report POST /api/tickets (session, or ALTCHA + rate limit + body cap while tickets.publicEnabled), the Bereiche (ticket_area/ticket_category, work right ticket.manage or the Gremium permission ticket.work, areas.py, /admin/ticket-areas), the work routes (list/counts/assignees/areas/detail/patch/notes), draft attachments bound with ticket_id, note files, the sender block (ticket_sender_block, "Absender sperren"), the mails ticket_created/ticket_received/ticket_message/ticket_answer, the "Hilfe & Tickets" settings (help.wikiUrl, tickets.publicEnabled/notifyNew/retentionMonths, GET/PUT /api/admin/help-tickets), the retention cron anonymize_tickets, privacy export/erasure and the search source. Use when working on tickets, the help menu backend, TicketService, ticket mails, ticket retention or ticket attachments in backend/app/modules/tickets.
---

# Tickets — `backend/app/modules/tickets`

**Does:** A person reports a bug, a question or an idea from the help menu. The answer is
`{ number }` only, and the reporter gets a confirmation mail. A reporter **account** then
reads its own tickets under `/tickets/mine` (the tab "Tickets" in the app): the report, the
`public` notes and the status changes, and it writes its own messages. A report without
an account stays one-way. Each ticket belongs to one **Bereich**. The team of a Bereich
works on its tickets: status, assignee, Kategorie, move to another Bereich, notes
(`internal` or `public`), a timeline of events and the technical context of the report.

**Key files:**
- `models.py` — `TicketSenderBlock` (see below), `Ticket` (number: eight random characters from `numbers.draw_number`, unique, `free_number` draws again on a used one; kind, status, reporter
  `reporter_principal_id` XOR `reporter_email` until `anonymized_at`, `assignee_id`,
  `duplicate_of_id`, `context` JSONB, `closed_at` = retention clock), `TicketNote` (soft
  delete, `visibility` `internal|public`, `author_id` NULL only for a reporter note on an
  anonymized ticket), `TicketEvent` (`created|status|assignee|kind|category|area|todo_done`),
  `TicketArea` (name unique, `gremium_id` nullable, `platform` with a one-row partial
  unique index, `notify_new`), `TicketCategory` (per Bereich, `position`, unique name per
  Bereich, deferrable). `Ticket.area_id` (default `PLATFORM_AREA_ID`), `Ticket.category_id`,
  `Ticket.kind` nullable (only a ticket of `Plattform` has a kind).
- `schemas.py` — wire models (camelCase). `TicketCreate` caps every string, because the
  route is public. `TicketPatch.assigneeId: null` unassigns (`model_fields_set`).
- `service.py` — `TicketService` (create, list with `q`, counts, assignees, detail with
  `contextTarget`, patch, notes, anonymize; every work method takes `areas: AreaScope`),
  `format_number`,
  `TicketTodoHooks` (the to-do coupling: `openTodoCount`, `completeTodos`, and
  `readable_cards`, so a `todo_done` event shows the card title only to a reader of its
  board; the implementation is `todos/hooks.py`).
- `router.py` — the routes; `get_ticket_service` is where the todos module wires its
  hooks; `get_ticket_mail_sender` is the override point for tests.
- `access.py` — `TICKET_MANAGE`, `TICKET_WORK`, `AreaScope` (`None` = every Bereich, else
  the ids), `area_scope(session, principal)`, `works_in`, `works_anywhere`, `area_workers`
  (the team of Bereiche: the holders of `ticket.manage` plus the members whose Gremium role
  has `ticket.work` in the Gremium of the Bereich), `works_on_ticket`, `works_on_tickets`.
- `areas.py` — `TicketAreaService` (listing with `mine`, create, patch, delete; no commit,
  the router commits; audit `config_change` on `ticket_area`).
- `mailbox.py` — `TicketMailboxService` (the Postfach of a Bereich: listing, create, patch,
  delete, test; no commit; audit `ticket_mailbox` on `ticket_area` with the names of the
  changed fields, never a password), `host_allowed`, `imap_account`, `smtp_account`.
  `mailbox_schemas.py` — `MailboxCreate`, `MailboxPatch`, `MailboxOut` (no password field).
  `mail_client.py` — `open_imap`, `open_smtp`, `check_imap`, `check_smtp`, `MailError`.
- Mails: `mails.py` and `mention_mails.py` (the texts are in `notifications/texts/tickets.py` and `texts/mentions.py`). Outside the module: `worker/tickets.py`
  (retention cron), `auth/people.py` (`PersonRef`, `person_of`, `person_refs`),
  `files/{drafts,service,router}.py` (ticket attachments), `site_config/branding.py`
  (`HelpSettings`, `TicketSettings`, `PublicBranding`), `site_config/reads.py` (`active_branding`) and `admin/site_config_service.py`
  (`help_tickets`, `put_help_tickets`).

**Bereiche and the work right (specs 002700 to 002707, 002715, 002717):**
- The built-in Bereich `Plattform` (`PLATFORM_AREA_ID`, seeded by the migration
  `e41b7d90a6c2`) takes every report of the help menu. It has no Gremium, its Kategorien
  are the four kinds, and nobody renames or deletes it (409 `ticket_area_platform_fixed`).
- A person works in a Bereich with `ticket.manage` (every Bereich) or with the Gremium
  permission `ticket.work` in the Gremium of the Bereich (forced roles `vorstand` and
  `manager` have it). The router dependency `require_worker` gives a `TicketWorker` with
  the scope: 403 without any Bereich, and a ticket outside the scope answers 404. The
  sender-block routes stay `ticket.manage`.
- `PATCH /tickets/{id}`: `categoryId` (a Kategorie of the Bereich of the ticket, null
  clears; 422 `category_invalid`; event `category` with both names) and `areaId` (move to
  any Bereich, also one the mover cannot read; 422 `area_invalid`; the move clears kind and
  Kategorie, clears the assignee without the right there, and writes the event `area` with
  `from`, `to`, `fromName`, `toName`). The answer of a move is the detail without the scope.
- `GET /tickets?area=` filters, `GET /tickets/assignees?area=` gives the team of one
  Bereich (404 outside the scope), `GET /tickets/areas` lists every Bereich with `mine`.
- `GET|POST /api/admin/ticket-areas`, `PATCH|DELETE /api/admin/ticket-areas/{id}`
  (`admin.site`): 409 `ticket_area_name_taken`, 409 `ticket_area_has_tickets`, 422
  `ticket_categories_invalid`. `categories` in a PATCH is the whole ordered list.

**Postfach of a Bereich (specs 002720, 002721, 002743 to 002746):**
- Table `ticket_mailbox` (model `TicketMailbox`): one row per Bereich (`area_id` unique),
  address, IMAP and SMTP host, port, user and password, `done_folder` (default `Erledigt`),
  `enabled` (default off), and the fetch state `uid_validity`, `last_uid`, `failures`,
  `last_error`, `fetched_at`. The passwords are plain text in the row, like the token of
  Paperless.
- `GET /api/admin/ticket-mailboxes` (`items`, `allowedHosts`), `POST|PATCH|DELETE
  /api/admin/ticket-areas/{id}/mailbox`, `POST /api/admin/ticket-areas/{id}/mailbox/test`,
  all behind `admin.ticket_mail`. No OAuth scope carries this permission, so no agent
  reaches the routes, and the MCP server has no tool for them.
- 409 `ticket_mailbox_exists` for a second Postfach, 422 `mail_host_not_allowed` (fields
  `imapHost`, `smtpHost`) for a host outside `TICKET_MAIL_HOST_ALLOWLIST` (entry = host or
  host:port; empty = no host).
- A PATCH holds only the changed fields; an empty password keeps the stored one. A change
  of the IMAP host, port or user resets `uid_validity` and `last_uid`, because the UIDs of
  another inbox mean other mails. Each change clears `failures` and `last_error`.
- `MailboxOut.error` shows only after 8 failed runs (`SHOWN_FAILURES`).
- TLS (002745): port 993 or 465 uses TLS from the start, each other port needs STARTTLS
  before the login; without it the client ends with `tls_missing` and sends no password.
  The certificate check is `ssl.create_default_context()`. A failed check answers a cause
  code (`tls_missing`, `tls_failed`, `timeout`, `login_failed`, `connect_failed`), never
  the text of the server.
- The switch (002722) is stored. The fetch and 409 `mailbox_off` do not exist yet.
- `GET /api/auth/me` carries `works_on_tickets`; the frontend `AuthService.worksOnTickets`
  opens the team view. Search, activity, to-do links (`works_on_ticket`) and the ticket
  attachments use the same scope.

**API surface:**
- `POST /api/tickets` — dependencies in the order of `POST /applications`:
  `enforce_ticket_payload_limit` (`MAX_TICKET_PAYLOAD_BYTES`, 64 KiB, 413),
  `rate_limit_tickets` (`tickets:ip:<ip>`, `RL_TICKETS_IP_PER_HOUR` 10, OAuth exempt),
  `require_public_or_session` (403 `tickets_public_disabled`),
  `verify_altcha_unless_authenticated` (400 `altcha_failed`). Without a session `email`
  is required (422). A session without an account row counts as no account.
  201 `{ number: "T-7K3QX9MD" }`.
- `GET /api/tickets` (`status`, `kind` repeatable; `assignee` = uuid | `me` | `none`; `q`
  matches title, body, number `T-7K3QX9MD` or a part such as `7k3q`, reporter name and e-mail; paged,
  newest first), `GET /api/tickets/counts`, `GET /api/tickets/assignees`,
  `GET|PATCH /api/tickets/{id}`, `POST /api/tickets/{id}/notes`,
  `PATCH|DELETE /api/tickets/{id}/notes/{noteId}` (403 `not_note_author`),
  `POST|DELETE /api/tickets/{id}/block-sender` (returns `TicketDetail`),
  `GET /api/tickets/blocked-senders`, `DELETE /api/tickets/blocked-senders/{blockId}` (204) — the
  work right of the Bereich (the block routes: `ticket.manage`); an unknown ticket or note is 404. PATCH 422 codes:
  `assignee_not_allowed` (not a holder), `duplicate_invalid` (`duplicateOfId` only with
  `rejected`, never itself).
- `GET /api/tickets/mine` (`status`, `kind`, `q`; paged), `GET /api/tickets/mine/{id}`
  (`ReporterTicketDetail`: report, files, `public` notes, `status` events without actor and
  without `duplicateOf`, `canReply`), `POST /api/tickets/mine/{id}/notes`
  (`ReporterNoteCreate`, always `public`; 403 `sender_blocked` while a block matches),
  `PATCH|DELETE /api/tickets/mine/{id}/notes/{noteId}` (own `public` messages; an
  `internal` note gives 404 like a missing one, a team note 403 `not_note_author`, an edit
  403 `sender_blocked` while a block matches, a delete stays allowed). The message and the
  edit lock the ticket row, because an anonymization between the check and the commit would
  miss the new note. Any session reads, no permission; a write needs a cookie session or a
  token whose scope allows `ticket.manage` (`tickets:write`), else 403. A ticket of another
  account, an anonymized ticket or a session without an account row gives 404 (list:
  empty page). The routes stand before `/tickets/{ticket_id}` so `mine` never parses as an
  id. The reporter sees no assignee, no context, no reporter block, no to-dos; a team author
  shows by name only: no e-mail fallback of `PersonRef` and no `principalId`, because the id
  opens the Gravatar of the e-mail. `updatedAt` also moves on internal activity.
- Mentions (`ticket_note.mentions`, migration `e7eeac24423f`): `NoteCreate.mentions` (≤ 50) and `NotePatch.mentions` (staff edit, null keeps) name holders of `ticket.manage` (the set of `GET /tickets/assignees`), else 422 `mention_not_member`. `TicketNoteOut.mentions` is `PersonRef[]`, empty for the reporter; the reporter routes take no mentions (`ReporterNoteCreate`, `NoteBody`) and the reporter edit keeps them. New mentions minus the author get `ticket_mentioned` after the commit (`get_mention_mail_sender`).
- `POST /api/tickets/{id}/notes` takes `visibility` (`internal` default, `public`);
  `TicketNoteOut` carries `visibility` and `fromReporter`.
- `GET /api/auth/me` carries `has_reported_tickets` (a ticket of the account that is not
  anonymized); the frontend shows the tab and lets the route guard pass (`allowReporter`).
- `GET|PUT /api/admin/help-tickets` (`admin.site`) — the direct save of the admin page.
- Public `GET /api/site-config` carries `help.wikiUrl` and `tickets.publicEnabled` top
  level; its `branding` omits `help` and `tickets` (`PublicBranding`).

**Data rules:**
- A status change writes a `status` event; entry into `done`/`rejected` sets `closed_at`,
  `done`→`rejected` keeps it, a reopen clears it. `duplicateOf` in the payload is the
  number. Assignee events store ids; the detail resolves them to `PersonRef`.
- Events get `created_at` from the process clock, because one PATCH can write two events
  and `now()` of the transaction would give them the same time.
- Attachments: the dialog uploads with `POST /api/apply/attachments` (draft token), then
  `POST /api/tickets` binds the drafts (`bind_drafts(..., ticket_id=...)`). The download
  route `GET /api/attachments/{id}/download` and the URL route need `ticket.manage` for a
  ticket attachment, or the reporter account (`reporter_reads_file`: a report file, or a
  file of a live `public` note; never on an anonymized ticket), else 404. Application paths filter `application_id IS NOT NULL`
  (`BOUND`), so a ticket file never shows there.
- Note files: `POST /notes` takes `NoteCreate` (`body` may be empty with a file,
  `attachmentIds` ≤ 5, `draftToken`) and binds with `ticket_note_id`; files on an
  anonymized ticket give 422 `ticket_anonymized`. With files `add_note` reads the ticket
  `FOR UPDATE`, and the cron `anonymize_tickets` and the erasure (`anonymize_reported_tickets`)
  lock it too, so a note cannot bind files
  between the check and the anonymization. `TicketNoteOut.attachments` lists them;
  `delete_note` and `delete_for_ticket` (anonymization, retention) remove them.
- **Sender block** (`ticket_sender_block`): exactly one of `principal_id` (the reporter
  account, cascade) or `email` (lowercase), plus `source_ticket_id`, `created_by`,
  `hit_count`, `last_hit_at`; a partial unique index per target, so a second block is a
  no-op. Blocking yourself (account or own account e-mail) is 422 `sender_is_self`; an
  anonymized or sender-less ticket is 409 `ticket_sender_unknown`. `TicketDetail.senderBlocked`
  and the per-ticket unblock use the same cross-identity condition as `matching_block`
  (`_sender_condition`): the flag shows every block that swallows the sender, and the
  unblock lifts all of them (account and account e-mail, or e-mail and its accounts).
  `create` checks `matching_block` after the draft check: an account matches by id or by
  its e-mail, an address matches the address or an account with it, case-insensitive. A
  match draws a number, counts the hit, commits and answers the normal
  201 `{ number }` (`SwallowedReport`) — no ticket row, no bound drafts, no mail. The log
  names the block id, never the address. The merge combines blocks; the erasure deletes
  them (be-privacy).
- `PersonRef`: name, else e-mail, else the deleted person (`null/null`).

**Mails:** `ticket_created` to the team of the Bereich (`area_workers`, not the reporter), only while
`notify_new` of the Bereich (the old branding value `tickets.notifyNew` became the switch of `Plattform`), opt-out kind, link `/tickets/{id}`. `ticket_received` to the reporter
(account e-mail or given e-mail) in `context.language`, else `de`, with `wikiUrl`; its kind
is not in `NOTIFICATION_KINDS`, so nobody can switch it off; only a report of an account
links `/tickets/{id}` (the tab), a report without a session stays one-way. A new `public`
message (`notify_ticket_note`, background task of both note routes, idempotency key per note)
goes to the other side (reporter messages capped by `rl_ticket_messages_per_hour`, 60/h per account): from the reporter as `ticket_message` to the assignee while they hold an address and
`ticket.manage`, else to every holder (never the reporter's own address); from the team as
`ticket_answer` to the live reporter account (active, not merged), with the author's name only; a message with neither text nor files sends nothing. Internal notes, edits,
anonymized tickets and reports without an account send nothing; a message of files only
names its files. Both kinds are opt-out. For a report
without a session the context `title` is empty, because that address is unchecked and the
platform must not mail the caller's text to it; the builtin texts drop the quoted title. Both run as
a background task after the commit and never fail the report.

**Retention and privacy:** `anonymize_tickets` (arq cron 03:45) anonymizes tickets whose
`closed_at` is older than `tickets.retentionMonths` (null = off): reporter, context and
attachments (row + object) go, title, body, notes and events stay, but the `created` event
loses its actor and the public notes of the reporter lose their author (both are the reporter; an internal note of the same account is team work and keeps it), one commit and one `anonymization` audit entry
per ticket. `PrincipalService.erase` gives the same anonymization to the tickets of the
account and to the reports without a session under the account's e-mail; an applicant
erasure does it for the tickets of the request's e-mail
(`privacy.service.anonymize_reported_tickets`). The Art. 15 export has a sheet "Tickets" (with text and context) and lists the ticket attachments in "Anhänge", and "Ticket-Sperren" lists the sender blocks. The account merge moves
reporter, assignee, note author and event actor (area `tickets`).

**Status, source and tickets by hand (specs 002708 to 002713, 002718):**
- Statuses `new|in_progress|waiting|done|rejected`. `waiting` ("Wartet auf Antwort") is open:
  `closed_at` stays empty, so the retention clock does not run (`OPEN` = not in
  `CLOSED_STATUSES`).
- A message of the sender (`reporter_add_note`) on a `waiting`, `done` or `rejected` ticket
  sets `in_progress` and writes a `status` event without an actor.
- `POST /api/tickets/mine/{id}/notes` first calls `reporter_follow_up`: when the close is
  more than `REOPEN_DAYS` (14) days old, the message becomes a new ticket in the same
  Bereich (`follow_up_of_id`, event `created` with `followUpOf`), and the answer is
  `{ followUp: { id, number } }` in place of the note. `ReporterTicketDetail.replyOpensNew`
  tells the app before the send. `TicketDetail.followUpOf` names the old ticket for the team.
- `Ticket.source` `help|mail|team` (`TICKET_SOURCES`; `mail` has no writer until the
  Postfach). The detail of the team shows it.
- `POST /api/tickets/manual` (`create_manual`, work right in the Bereich): a ticket for an
  account, source `team`. `body` is the note of the team and the view of the person leaves
  it out (`reporter_detail`, the search of `reporter_list`); `message` becomes the first
  public note and sends `ticket_answer`. An e-mail address answers 422
  `ticket_area_without_mailbox`, because no Bereich has a Postfach yet. An unknown, inactive
  or merged account, or both or neither of `reporterId` and `email`: 422
  `ticket_reporter_invalid`.
- `ticket_area.in_app` ("In der App erreichbar"): `GET /api/tickets/report-areas`
  (`TicketAreaService.choices`: `Plattform` plus each Bereich with the switch) feeds the
  dialog of the help menu. `POST /api/tickets` takes `areaId` and `categoryId`
  (`_report_area`, `_check_kind`): without a session only `Plattform` (403
  `ticket_area_needs_session`), a Bereich without the switch 403
  `ticket_area_not_reachable`, `Plattform` needs a `kind`, another Bereich takes no kind.
- Mail `ticket_assigned` (`notify_ticket_assigned`, opt-out kind of the team): to the new
  assignee when a different person assigned the ticket. It reads the newest `assignee`
  event, so a take-over by the own account sends nothing; idempotent per event id.
- `create_manual` and `reporter_follow_up` do not commit (ratchet `service-commits`); the
  router commits.
- The migration `a8c3f15d7e42` (idempotent) widens `ck_ticket_status`, adds `ticket.source`,
  `ticket.follow_up_of_id` and `ticket_area.in_app`.

**Search:** source `ticket` behind the work right (the Bereiche of the reader), reuses `TicketService.list`; title
`T-7K3QX9MD · <title>`, subtitle the status in the reader's language, url `/tickets/{id}`.

**Conventions & gotchas:**
- The migration `071d20ab0e10` adds `ticket_note.visibility` (existing notes stay
  `internal`) and drops `NOT NULL` from `ticket_note.author_id`.
- The migration `269d13cd80a8` adds the three message owners of `attachment` and
  `ticket_sender_block` (idempotent, with a downgrade).
- The migration `86718c748401_tickets` is idempotent (baseline `create_all` already builds
  the tables) and widens `ck_attachment_draft_xor_application` to three owners.
- `TicketContext.url` keeps a platform page only: an http(s) URL on the origin of
  `PUBLIC_BASE_URL` or a path with one leading `/` (`platform_page_url`). Any other value is
  dropped, not rejected, because the detail shows it as a link and the route is public.
- `scripts/check_functional.py` counts every attribute assignment as a binding: set several
  columns with `for name, value in values.items(): setattr(row, name, value)`.
- `ticket.manage` is in `PERMISSION_CATALOGUE`, granted to the `admin` role by the
  migration, and in the OAuth scope `tickets:write`.
- The unit coverage gate counts unit tests only: `tests/unit/modules/tickets` uses a
  scripted session (`fakes.py`); `tests/integration/modules/tickets` runs on Postgres.

**Related:** be-todos, be-files, be-antiabuse, be-notifications, be-admin, be-privacy,
be-search, be-auth, frontend
