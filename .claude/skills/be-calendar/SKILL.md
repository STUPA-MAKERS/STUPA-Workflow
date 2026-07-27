---
name: be-calendar
description: Backend calendar/ICS module. It serves a personal token-authenticated iCal subscription feed (text/calendar, RFC5545 VCALENDAR) of the meetings of every gremium a principal belongs to. It also reads and rotates the feed token. Triggers: calendar_token, .ics feed, iCal subscription, MeetingEvent, build_calendar, /calendar routes. Use when working on the ICS calendar feed in backend/app/modules/calendar.
---

# Calendar / ICS Feed — `backend/app/modules/calendar`

**Does:** Serves a personal token-authenticated iCal (`.ics`) subscription feed. The feed lists the dated meetings of every gremium the token owner belongs to. Calendar clients cannot do OIDC, so a rotatable per-principal feed token authenticates the public feed URL.

**Key files:**
- `router.py` — the `/calendar` `APIRouter` with the three endpoints, the `_feed_url`/`_uid_domain` helpers and the `text/calendar` response building.
- `service.py` — token CRUD + data access: generate/get/rotate token, resolve principal by token, `member_meetings` query. It does NOT commit. The caller commits.
- `ics.py` — pure RFC5545 builder: `MeetingEvent` dataclass, `build_calendar()` → `bytes`. No DB. The module imports `icalendar` lazily, only on the feed path.
- `schemas.py` — `CalendarFeedOut {url: str | None}`.
- `__init__.py` — module docstring (`#ics`).

**Domain / data model:**
- The feed token lives on `Principal.calendar_token` (`auth/models.py`): `Text`, nullable, UNIQUE (`uq_principal_calendar_token`). The `Principal.active` bool gates feed access. The service resolves a `Principal` by `sub` (string), not by the DB `id`, so the service functions take `principal.sub`.
- Token = `secrets.token_urlsafe(32)` (~43 URL-safe chars, no `.` or `/`). It is stored in cleartext on purpose. The token has low sensitivity, because it exposes only the titles and times of the meetings of the gremien the principal belongs to. A rotation invalidates the old URL.
- The meetings come from `livevote.models.Meeting` (`id`, `title`, `gremium_id`, `date`, `start_time`, `end_time`, `created_at`). The query joins the gremium name from `admin.models.Gremium`. `member_meetings` filters `date IS NOT NULL`, orders by `date, start_time` and returns `(Meeting, gremium_name)` pairs. Membership comes from `admin.gremium_roles.gremium_member_ids(db, sub)`.
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

**Related:** be-livevote, be-admin, be-auth
