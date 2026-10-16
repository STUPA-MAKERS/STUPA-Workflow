---
name: be-tickets
description: Tickets from the help menu — problem reports, questions and ideas (ticket/ticket_note/ticket_event, number T-0001 from ticket_number_seq). Covers the public one-way report POST /api/tickets (session, or ALTCHA + rate limit + body cap while tickets.publicEnabled), the ticket.manage work routes (list/counts/assignees/detail/patch/notes), draft attachments bound with ticket_id, the mails ticket_created/ticket_received, the "Hilfe & Tickets" settings (help.wikiUrl, tickets.publicEnabled/notifyNew/retentionMonths, GET/PUT /api/admin/help-tickets), the retention cron anonymize_tickets, privacy export/erasure and the search source. Use when working on tickets, the help menu backend, TicketService, ticket mails, ticket retention or ticket attachments in backend/app/modules/tickets.
---

# Tickets — `backend/app/modules/tickets`

**Does:** A person reports a bug, a question or an idea from the help menu. The report is
one-way: the answer is `{ number }` only, the reporter gets a confirmation mail and never
reads the ticket again. Holders of `ticket.manage` work on the tickets: status, assignee,
kind, internal notes, a timeline of events and the technical context of the report.

**Key files:**
- `models.py` — `Ticket` (number from `ticket_number_seq`, kind, status, reporter
  `reporter_principal_id` XOR `reporter_email` until `anonymized_at`, `assignee_id`,
  `duplicate_of_id`, `context` JSONB, `closed_at` = retention clock), `TicketNote` (soft
  delete), `TicketEvent` (`created|status|assignee|kind|todo_done`).
- `schemas.py` — wire models (camelCase). `TicketCreate` caps every string, because the
  route is public. `TicketPatch.assigneeId: null` unassigns (`model_fields_set`).
- `service.py` — `TicketService` (create, list with `q`, counts, assignees, detail with
  `contextTarget`, patch, notes, anonymize), `ticket_managers` (role assignments plus OIDC
  group mappings plus the admin role; active, not merged), `format_number`,
  `TicketTodoHooks` (the to-do coupling: `openTodoCount`, `completeTodos`, and
  `readable_cards`, so a `todo_done` event shows the card title only to a reader of its
  board; the implementation is `todos/hooks.py`).
- `router.py` — the routes; `get_ticket_service` is where the todos module wires its
  hooks; `get_ticket_mail_sender` is the override point for tests.
- `access.py` — `TICKET_MANAGE`.
- Outside the module: `notifications/tickets.py` (both mails), `worker/tickets.py`
  (retention cron), `shared/people.py` (`PersonRef`, `person_of`, `person_refs`),
  `files/{drafts,service,router}.py` (ticket attachments), `admin/branding.py`
  (`HelpSettings`, `TicketSettings`, `PublicBranding`), `admin/site_config_service.py`
  (`active_branding`, `help_tickets`, `put_help_tickets`).

**API surface:**
- `POST /api/tickets` — dependencies in the order of `POST /applications`:
  `enforce_ticket_payload_limit` (`MAX_TICKET_PAYLOAD_BYTES`, 64 KiB, 413),
  `rate_limit_tickets` (`tickets:ip:<ip>`, `RL_TICKETS_IP_PER_HOUR` 10, OAuth exempt),
  `require_public_or_session` (403 `tickets_public_disabled`),
  `verify_altcha_unless_authenticated` (400 `altcha_failed`). Without a session `email`
  is required (422). A session without an account row counts as no account.
  201 `{ number: "T-0042" }`.
- `GET /api/tickets` (`status`, `kind` repeatable; `assignee` = uuid | `me` | `none`; `q`
  matches title, body, number `T-0040`/`0040`/`40`, reporter name and e-mail; paged,
  newest first), `GET /api/tickets/counts`, `GET /api/tickets/assignees`,
  `GET|PATCH /api/tickets/{id}`, `POST /api/tickets/{id}/notes`,
  `PATCH|DELETE /api/tickets/{id}/notes/{noteId}` (403 `not_note_author`) — all
  `ticket.manage`; an unknown ticket or note is 404. PATCH 422 codes:
  `assignee_not_allowed` (not a holder), `duplicate_invalid` (`duplicateOfId` only with
  `rejected`, never itself).
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
  ticket attachment, else 404. Application paths filter `application_id IS NOT NULL`
  (`BOUND`), so a ticket file never shows there.
- `PersonRef`: name, else e-mail, else the deleted person (`null/null`).

**Mails:** `ticket_created` to the holders of `ticket.manage` (not the reporter), only while
`tickets.notifyNew`, opt-out kind, link `/tickets/{id}`. `ticket_received` to the reporter
(account e-mail or given e-mail) in `context.language`, else `de`, with `wikiUrl`; its kind
is not in `NOTIFICATION_KINDS`, so nobody can switch it off, and it has no link. For a report
without a session the context `title` is empty, because that address is unchecked and the
platform must not mail the caller's text to it; the builtin texts drop the quoted title. Both run as
a background task after the commit and never fail the report.

**Retention and privacy:** `anonymize_tickets` (arq cron 03:45) anonymizes tickets whose
`closed_at` is older than `tickets.retentionMonths` (null = off): reporter, context and
attachments (row + object) go, title, body, notes and events stay, but the `created` event
loses its actor (that actor is the reporter), one commit and one `anonymization` audit entry
per ticket. `PrincipalService.erase` gives the same anonymization to the tickets of the
account and to the reports without a session under the account's e-mail; an applicant
erasure does it for the tickets of the request's e-mail
(`privacy.service.anonymize_reported_tickets`). The Art. 15 export has a sheet "Tickets". The account merge moves
reporter, assignee, note author and event actor (area `tickets`).

**Search:** source `ticket` behind `ticket.manage`, reuses `TicketService.list`; title
`T-0040 · <title>`, subtitle the status in the reader's language, url `/tickets/{id}`.

**Conventions & gotchas:**
- The migration `86718c748401_tickets` is idempotent (baseline `create_all` already builds
  the tables) and widens `ck_attachment_draft_xor_application` to three owners.
- `TicketContext.url` keeps a platform page only: an http(s) URL on the origin of
  `PUBLIC_BASE_URL` or a path with one leading `/` (`platform_page_url`). Any other value is
  dropped, not rejected, because the detail shows it as a link and the route is public.
- `ticket.manage` is in `PERMISSION_CATALOGUE`, granted to the `admin` role by the
  migration, and in the OAuth scope `tickets:write`.
- The unit coverage gate counts unit tests only: `tests/unit/modules/tickets` uses a
  scripted session (`fakes.py`); `tests/integration/modules/tickets` runs on Postgres.

**Related:** be-todos, be-files, be-antiabuse, be-notifications, be-admin, be-privacy,
be-search, be-auth, frontend
