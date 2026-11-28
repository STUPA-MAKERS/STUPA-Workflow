---
name: be-events
description: Veranstaltungen (Events) as an element of their own with a team (table event, number V-7K3QX9MD), not a card. Covers the fields (dates and times, place, participants, series, shop link), the status of the configured list `event` (module `statuses`, page Veranstaltungszustände), the rights (a member of the team; 404 for others; token scope todos:write), the totals and decisions from the links, one Event per Antrag/Buchung/invoice, the series and the other editions, the segments upcoming/past/done/void, the search, the calendar entries, the Buchung picker, the export, the webhook events event.*, the migration of the old event cards, the MCP tools event_* and the frontend page "Veranstaltungen" (/events). Use when working on backend/app/modules/events or frontend/src/app/pages/events.
---

# Veranstaltungen — `backend/app/modules/events`

**Does:** An Event is an element of its own with a team (specs
`specs/requirements/functional/collaboration/events/003022-003034`, `003041`, and the
still valid 000479-000483, 000736). It moves no money: its totals come from the Anträge,
Buchungen and invoices that a link joins to it. **No code names a status key, a team or a
Gremium**; the status keys come from the list `event` of `app/modules/statuses`, and the
code reads only the phase (`open`, `done`, `void`).

**Key files:**
- `models.py` — `Event` (`team_id` RESTRICT, `number`, `title`, `status`, `description_md`,
  `starts_on`/`start_time`/`ends_on`/`end_time`, `place`, `participants`, `series_id` →
  `todo_event_series` SET NULL, `shop_url`, `version`, `created_by`) and
  `format_event_number` (`V-`).
- `rules.py` — pure: `Segment`, `segment_of(phase, starts_on, ends_on, today)`,
  `dates_problem` (codes `event_dates_invalid`, `event_time_without_date`), `shop_valid`
  (reuses `orders.rules.url_valid`).
- `access.py` — `event_team_ids(session, principal)`: the teams of the caller
  (`teams.members.member_team_ids`); a token needs the scope of `todo.write`.
- `facts.py` — `Totals`, `totals`, `Decision`, `decisions`, `series_names`, `editions`
  (the other editions of a series and the count the reader cannot read),
  `check_one_event` (409 `event_link_taken`), `balance_text`. `KIND = "event"`.
- `listing.py` — `EventFilter`, `segment_clause`, `EventListing.page` (trigram search on
  number, title and place; "V-" is stripped).
- `service.py` — `EventService(session, today)`: `get` (404 for a non-member), `create`
  (403 `event_team_forbidden`, 422 `event_url_invalid`/`series_not_found`/`status_unknown`),
  `update` (409 `event_version_conflict`, the dates checked after the merge, a team
  change), `set_status`, `delete`, `views`, `detail`, `refs` (open phase: the Buchung
  picker), `series`, `create_series`. Each write emits its webhook event; the router
  commits.
- `router.py` — `GET/POST /events`, `GET /events/teams`, `GET /events/refs`,
  `GET/POST /events/series`, `GET /events/export.xlsx` (`finance.export`, audit `EXPORT`),
  `GET/PATCH/DELETE /events/{id}`, `POST /events/{id}/status`. Feature switch
  `Feature.EVENTS` gates `/events` (`feature_routes.py`).
- `webhook_fields.py` — `event_fields`, `emit_event_event` (ids `eventId`; the Gremium
  filter reads the Gremium of the inherent team).
- `calendar.py` — `events_between` for the Kalender (`calendar/entries.py`,
  `calendar/service.py` feed, `ics.CardEvent` with `team_name`).

**Links:** the link kind `event` lives in `todos/models.py` (`LINK_KINDS` after `order`)
and `todos/links.py` (`_events`, `_event_target` → `/events?id=`, `_event_candidates`);
`link_rights.py` lets a team member change it; `link_service.py` sorts an Event first and
calls `check_one_event` on an add.

**Migration `7c4e2a9d1b85`:** creates `event`, adds the kind to the link checks and the
trigger `link_drop_ends`, turns each event card into an Event (the team of the board, else
the single team entry, else a new team), copies the links of the card, links the card to
its Event (ends in byte order, `Link.between`) and drops `todo_card_event`. The downgrade
rebuilds `todo_card_event` from the card links.

**Other users:** search (`HIT_URL` `/events?id=`), graph (`relations.py`, the date
`starts_on`), account merge (`Event.created_by`), webhook catalog (group `events`),
MCP `mcp/antragsplattform_mcp/tools/events.py`.

**Tests:** unit `tests/unit/modules/events/`; integration
`tests/integration/modules/todos/test_todos_events.py` (rights, totals, series,
segments, search, calendar, export, webhooks) and `test_migrations.py::
test_event_cards_become_events`.

## pretix and Mollie (`event_sales`, `pretix`, `mollie`)

Specs `specs/requirements/functional/integrations/pretix/003080-003091`,
`mollie/003092-003104`, `mcp/003102` and `non-functional/security/network/003100-003101`.

- `app/modules/pretix/` — `client.py` (GET only, allowlist `PRETIX_HOST_ALLOWLIST`, no
  redirect, an `Order` without personal values), `rules.py` (pure: `sales_of`,
  `candidates`), `connection.py` (one row, sealed token, switches `show_sales` and
  `book_income`), `models.py` (`pretix_settings`, `pretix_event_link`, `pretix_booking`).
- `app/modules/mollie/` — `client.py` (GET only, `api.mollie.com` only, money values only),
  `connection.py`, `models.py` (payments, refunds/chargebacks, settlements, bookings).
- `app/modules/event_sales/` (top layer) — `sync.run` holds the advisory lock
  (409 `sync_running`); `pretix_sync`, `mollie_sync` read and book; `booking.book` makes
  each booking in a savepoint with the author `Pretix`/`Mollie` and returns the cause
  code of a failure; the fees of a settlement get one sub-booking per Event plus the rest;
  `router.py` has `/admin/pretix`, `/admin/mollie`, `/pretix/events`, `/pretix/links/{id}`,
  `/events/{id}/sales(/refresh)` and `/sales-sync`. Every route that links or calls pretix
  or Mollie refuses an agent token (`refuse_agent_token`). Tests override
  `get_factories` with `tests/_support/sales_fakes.py`.
- Worker `worker/event_sales.py`: pretix every 15 minutes, Mollie hourly.
- Frontend: `pages/events/event-sales.component.ts` (section "Verkauf"),
  `event-pretix-link.ts` (the two form fields), `shared/sales-sync.ts` ("Daten abrufen"),
  `pages/admin/pretix`, `pages/admin/mollie`, `pages/admin/sales-admin.ts`.
- Trap: a Mollie payment of a pretix event that no Event links yet is booked on the
  Kostenstelle without an Event (003103); a later link books the pretix order too.
