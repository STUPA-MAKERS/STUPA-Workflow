---
name: be-calendar
description: Backend calendar module. It serves the entries of the Kalender page (meetings, due cards, Events, Termine) and their search, the Termine (calendar_appointment) with invitations of Gremien and persons, answers and mails with an .ics file, and the personal token-authenticated iCal subscription feed. Triggers: Termin, Appointment, Invitation, Answer, AppointmentService, CalendarEntries, calendar.manage, calendar.publish, calendar_token, .ics feed, build_calendar, /calendar routes. Use when working on the Kalender, Termine or the ICS feed in backend/app/modules/calendar.
---

# Calendar / ICS Feed — `backend/app/modules/calendar`

**Does:** Serves a personal token-authenticated iCal (`.ics`) subscription feed. The feed lists the dated meetings of every Gremium the token owner belongs to, and the open to-do cards assigned to the owner that have a due date, as all-day events (spec 000549, `service.due_cards` → `TodoService.calendar_due_cards`). Calendar clients cannot do OIDC, so a rotatable per-principal feed token authenticates the public feed URL.

**Key files:**
- `router.py` — the `/calendar` `APIRouter` with the three endpoints, the `_feed_url`/`_uid_domain` helpers and the `text/calendar` response building.
- `service.py` — token CRUD + data access: generate/get/rotate token, resolve principal by token, `member_meetings` query. It does NOT commit. The caller commits.
- `ics.py` — pure RFC5545 builder: `MeetingEvent` and `DueCard` dataclasses, `build_calendar(..., due_cards=)` → `bytes`. No DB. The module imports `icalendar` lazily, only on the feed path.
- `schemas.py` — `CalendarFeedOut {url: str | None}`.
- `__init__.py` — module docstring (`#ics`).

**Domain / data model:**
- The feed token lives on `Principal.calendar_token` (`auth/models.py`): `Text`, nullable, UNIQUE (`uq_principal_calendar_token`). The `Principal.active` bool gates feed access. The service resolves a `Principal` by `sub` (string), not by the DB `id`, so the service functions take `principal.sub`.
- Token = `secrets.token_urlsafe(32)` (~43 URL-safe chars, no `.` or `/`). It is stored in cleartext on purpose. The token has low sensitivity, because it exposes only the titles and times of the meetings of the Gremien the principal belongs to. A rotation invalidates the old URL.
- The meetings come from `livevote.models.Meeting` (`id`, `title`, `gremium_id`, `date`, `start_time`, `end_time`, `created_at`). The query joins the Gremium name from `gremien.models.Gremium`. `member_meetings` filters `date IS NOT NULL`, orders by `date, start_time` and returns `(Meeting, gremium_name)` pairs. Membership comes from `gremien.gremium_roles.gremium_member_ids(db, sub)`.
- `MeetingEvent`: `uid`(=meeting id), `title`, `date`(required), `start_time|None`, `end_time|None`, `stamp`(=created_at → DTSTAMP), `gremium_name|None`.

**API surface:**
- `GET /api/calendar/me` — read the own subscription URL (`null` until a token exists). Requires a principal (401).
- `POST /api/calendar/me/rotate` — generate the feed token again. The old URL stops working. This route commits.
- `GET /api/calendar/{token}.ics` — **public** and token-authenticated. An unknown, inactive or empty token gives 404, and the answer never tells a wrong token apart from a deactivated principal. Returns `text/calendar; charset=utf-8`, `Content-Disposition: inline`, `Cache-Control: private, max-age=300`.

**Conventions & gotchas:**
- Event UIDs are `meeting-{id}@{domain}`. The domain is the hostname of `settings.public_base_url`, with the fallback `stupa.local`. The UID stays stable across re-renders, so the client de-duplicates.
- `Meeting` stores LOCAL `Europe/Berlin` naive `time` values. `ics.py` converts them to UTC and emits `…T…Z` with no `VTIMEZONE` block. `zoneinfo` resolves DST (CET/CEST) per date. A meeting without a `start_time` becomes an all-day `VALUE=DATE` event with no DTEND.
- The builder uses `end_time` only when it is strictly `> start_time`. Otherwise it applies `DEFAULT_DURATION = 1h`. Each event carries a `VALARM` DISPLAY reminder: 1h before a timed event, 1 day before an all-day event.
- The service functions never commit. The router calls `db.commit()` in `/me/rotate`. The feed read path is read-only.
- `build_calendar` is a pure function. It touches no DB and imports `icalendar` lazily, like openpyxl and minio. That keeps it easy to unit-test. The service must pass `events` already filtered and sorted.

## Kalender page and Termine (specs `meetings/calendar` 000710-000738)

**Key files:**
- `models.py` — `Appointment` (`calendar_appointment`: title, `starts_on`/`ends_on`, `start_time`/`end_time` NULL = all-day, place, description, `creator_id` SET NULL, `for_all`, `sequence`), `Invitation` (exactly one of `gremium_id`/`principal_id`), `Answer` (PK appointment + principal; `accept`/`tentative`/`decline`).
- `rules.py` — the pure rules: `Viewer`, `Targets`, `Span`, `can_read`, `is_invited`, `can_edit`, `sees_answers`, `time_changed`, `needs_mail`, `has_ended`, `forbidden_gremien`.
- `appointments.py` — `AppointmentService` (create, update, delete, answer, `between`, `matching`, `people_search`) and the SQL forms `readable`/`mine`. A write returns `Written(out, mails)`; the router commits and sends the mails as a background task.
- `entries.py` — `CalendarEntries.between`/`search`: the entries of the page, each kind under the rule of its own module (`MeetingRules.meeting_read_scope`, `TodoService.calendar_due_between`/`calendar_events_between`, `appointments.readable`).
- `mails.py` — one mail per person with the `.ics` file (`build_appointment_file`), notification kind `appointment`, templates `appointment_invited`/`_changed`/`_cancelled` (`notifications/texts/calendar.py`).
- `privacy.py` — `erase_appointments`, `appointment_export` (called by `privacy/service.py`). The account merge handles the three principal columns in `admin/principal_merge.py`.

**API surface:**
- `GET /api/calendar/entries?from&to&mine` — at most 100 days. `mine` limits the cards and Events to the assigned ones and the Termine to created or invited.
- `GET /api/calendar/search?q` — two characters or more, every month, the nearest to today first.
- `GET /api/calendar/people?q` — id and name of the active accounts, never an address (000738).
- `POST /api/calendar/appointments`, `GET|PUT|DELETE /api/calendar/appointments/{id}`, `PUT …/{id}/answer`.

**Conventions & gotchas:**
- An invited Gremium stands for its members and its substitute pool at the time of the read (`gremium_person_ids`, `gremium_reader_ids`). `meeting.view_all` invites nobody.
- The creator invites only a Gremium whose meetings the creator reads; a Gremium that the Termin invites already stays. `calendar.manage` invites any Gremium and edits every Termin. Only `calendar.publish` changes `for_all`.
- A read without the right answers 404. A scoped OAuth token has no `Viewer.id` and reads and writes no Termin, because no OAuth scope names the Kalender.
- A change of the start or the end deletes the answers. A change of the start, the end or the place raises `sequence` and mails the invited persons. The actor never gets a mail.
- `update` and `answer` write with statements, not through attribute writes, because of the functional ratchet. `load` therefore reads the answers with `populate_existing`.
- The feed holds every readable Termin (`service.feed_appointments`). An invited owner is the `ATTENDEE` with the answer as `PARTSTAT`.

**Related:** be-livevote, be-admin, be-auth, be-todos, be-notifications, be-privacy

## External calendars (specs 000721-000724, 000729)

- Tables `calendar_external` (`ExternalCalendar`: name, url, `gremium_id` or NULL for all, `interval_minutes` of `FETCH_INTERVALS`, `due_at`, `last_attempt_at`, `last_success_at`, `last_error`) and `calendar_external_entry` (`ExternalEntry`, deleted with its calendar).
- `external.py` `ExternalCalendarService`: the admin writes, `due`/`refresh` of the worker and the reads (`between`, `matching`, `readable`, `entry`). An entry of a calendar for all is readable by each signed-in person; an entry of a Gremium calendar follows `MeetingRules.meeting_read_scope`.
- The API never fetches, because a request must not wait on a foreign host. A create, a new address and `POST /admin/calendars/{id}/fetch` set `due_at` to now; `worker/calendars.py` `fetch_external_calendars` (cron, each minute) fetches at most `BATCH` due calendars, each in its own transaction with a row lock.
- `external_fetch.py` `HttpFeedFetcher`: https only, the SSRF guard (`app/shared/ssrf.py`) on every hop, at most 3 redirects, 10 s, 2 MB. A failure is a code (`blocked`, `timeout`, `unreachable`, `status`, `size`, `redirect`, `format`) in `last_error`, and the entries of the last good fetch stay.
- `external_feed.py` `parse_feed`: only title, start, end, place and description, as plain text (`plain`), never an organiser or an attendee. Times are local Berlin values. A series is expanded 12 months back and 24 ahead (`MAX_SERIES`, `MAX_ENTRIES`).
- Routes: `GET /api/calendar/external/{entry_id}`; `/api/admin/calendars` GET/POST, `/{id}` PUT/DELETE, `/{id}/fetch` POST, all behind `admin.calendars`. `entries.py` adds the kind `external` to the span and the search, and the personal feed holds the readable entries (`service.feed_external`, `ics.ExternalEvent`).

## Public calendar (specs 000730-000734)

- `Appointment.public` (the switch "Öffentlich", migration `a4c8e17d5f02`): only `calendar.publish` sets or changes it, like "Für alle". A public Termin is readable by each signed-in person too (`appointments.readable`).
- `public.py` `PublicCalendarService`: the reads without a sign-in. Two kinds and no other: a public Termin and a meeting of a Gremium with `protocols_public`. A public Termin gives title, start, end, place and description, never its creator, invitations or answers, so its entry has no Gremium and a filter by Gremium keeps only meetings. A public meeting gives title, day, times, the Gremium name, the titles of the TOPs with `non_public` false, and `protocolId` when the public protocol exists (`protocol.public.visible_clause`).
- `public_router.py`, all under `/api/public` (the security middleware adds `X-Robots-Tag: noindex`), with the rate limit of the public protocols page: `calendar/committees`, `calendar/entries?from&to&gremium`, `calendar/search?q`, `calendar/appointments/{id}`, `calendar/meetings/{id}`, `calendar.ics`.
- The feed has no token and no `ORGANIZER`/`ATTENDEE`. `RedisFeedCache` keeps its bytes for `FEED_TTL_SECONDS` (300) and fails open. A new public route needs an entry in `PUBLIC_ROUTES` (`tests/unit/test_public_routes.py`).

