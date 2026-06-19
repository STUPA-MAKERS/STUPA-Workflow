---
name: be-calendar
description: Backend calendar/ICS module — a personal token-authenticated iCal subscription feed (text/calendar, RFC5545 VCALENDAR) of meetings for the gremien a principal belongs to, plus read/rotate of the feed token. Triggers - calendar_token, .ics feed, iCal subscription, MeetingEvent, build_calendar, /calendar routes. Use when working on the ICS calendar feed in backend/app/modules/calendar.
---

# Calendar / ICS Feed — `backend/app/modules/calendar`

**Does:** Serves a personal, token-authenticated iCal (`.ics`) subscription feed listing the dated meetings of every gremium the token-owner is a member of. Calendar clients can't do OIDC, so a rotatable per-principal feed token authenticates the public feed URL.

**Key files:**
- `router.py` — `/calendar` `APIRouter`; the three endpoints, `_feed_url`/`_uid_domain` helpers, `text/calendar` Response building.
- `service.py` — token CRUD + data access: generate/get/rotate token, resolve principal by token, `member_meetings` query. Does NOT commit (callers do).
- `ics.py` — pure RFC5545 builder: `MeetingEvent` dataclass, `build_calendar()` → `bytes`. No DB. `icalendar` imported lazily (only on the feed path).
- `schemas.py` — `CalendarFeedOut {url: str | None}`.
- `__init__.py` — module docstring (`#ics`).

**Domain / data model:**
- Feed token lives on `Principal.calendar_token` (`auth/models.py`): `Text`, nullable, UNIQUE (`uq_principal_calendar_token`). `Principal.active` bool gates feed access. `Principal` is resolved by `sub` (string), not DB `id` — service fns take `principal.sub`.
- Token = `secrets.token_urlsafe(32)` (~43 URL-safe chars, no `.`/`/`). Stored in cleartext (deliberate: low-sensitivity, exposes only meeting titles/times of one's own gremien). Rotating invalidates the old URL.
- Meetings sourced from `livevote.models.Meeting` (`id`, `title`, `gremium_id`, `date`, `start_time`, `end_time`, `created_at`); gremium name joined from `admin.models.Gremium`. `member_meetings` filters `date IS NOT NULL`, orders by `date, start_time`, returns `(Meeting, gremium_name)` pairs. Membership comes from `admin.gremium_roles.gremium_member_ids(db, sub)`.
- `MeetingEvent`: `uid`(=meeting id), `title`, `date`(required), `start_time|None`, `end_time|None`, `stamp`(=created_at → DTSTAMP), `gremium_name|None`.

**API surface:**
- `GET /api/calendar/me` — read own subscription URL (`null` until a token exists). Requires principal (401).
- `POST /api/calendar/me/rotate` — (re)generate feed token, invalidating the prior URL; commits.
- `GET /api/calendar/{token}.ics` — **public**, token-authenticated; unknown/inactive/empty token → 404 (no distinction between wrong-token and deactivated). Returns `text/calendar; charset=utf-8`, `Content-Disposition: inline`, `Cache-Control: private, max-age=300`.

**Conventions & gotchas:**
- Event UIDs are `meeting-{id}@{domain}`, domain = hostname of `settings.public_base_url` (fallback `stupa.local`) — stable across re-renders so client de-dupes.
- Times are LOCAL `Europe/Berlin` naive `time`s on `Meeting`; `ics.py` converts to UTC and emits `…T…Z` (no `VTIMEZONE` block); DST (CET/CEST) resolved per-date via `zoneinfo`. Meetings with no `start_time` become all-day `VALUE=DATE` events (no DTEND).
- `end_time` used only if strictly `> start_time`; otherwise `DEFAULT_DURATION = 1h`. Each event carries a `VALARM` DISPLAY reminder: 1h before (timed) / 1 day before (all-day).
- Service functions never commit; router `/me/rotate` calls `db.commit()` explicitly. Feed read path is read-only.
- `build_calendar` is a pure function (DB-free, lazily imports `icalendar` like openpyxl/minio) — easy to unit-test; `events` must already be filtered+sorted by the service.

**Related:** be-livevote, be-admin, be-auth
