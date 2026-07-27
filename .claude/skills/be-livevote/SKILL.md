---
name: be-livevote
description: Meetings — planned→live→closed lifecycle, agenda items, attendance roster, and live voting over WebSocket. The WebSocket layer has a voter channel plus a read-only beamer stream, and the meeting start creates the protocol. Use when working on meetings, agenda items, attendance, live-vote casting/tally, the meeting:{id} pub/sub channel, or MeetingService in backend/app/modules/livevote.
---

# Live-Vote / Meetings — `backend/app/modules/livevote`

**Does:** Manages Gremium meetings: CRUD plus lifecycle control, agenda items, and attendance. It also runs a Redis pub/sub live-vote channel with a voter WebSocket (cast/subscribe) and a read-only beamer stream. This is the second-largest backend module. The service creates the protocol lazily when a meeting goes live.

**Key files:**
- `models.py` — `Meeting`, `MeetingAttendance`, `MeetingAgendaItem` ORM tables.
- `schemas.py` — Pydantic API I/O (`MeetingCreate/Patch/Out`, `MeetingVoteOut`, `MeetingPage`, agenda + attendance bodies) with camelCase aliases and `populate_by_name`.
- `events.py` — WS message contract (single source): server→client `meeting_state|vote_opened|vote_tally|vote_closed|vote_cancelled|viewers|error`, client→server `cast|subscribe`. `VoteTallyEvent.from_vote` enforces the "counts only at close" secrecy rule.
- `router.py` — REST routes plus the two WS endpoints. It holds the per-(meeting,principal) connection cap and the field-level RBAC gating. On `planned→live` it creates the protocol.
- `service.py` — `MeetingService` (lifecycle, timeline, RBAC, vote decoration) plus `BrokerPublisher`. `BrokerPublisher` builds WS events from voting schemas and implements the leaf `MeetingPublisher` protocol, so `voting` does not import `livevote`. `meeting_channel(id)` → `meeting:{id}`.
- `agenda_service.py` — `AgendaService`: assign/remove/reorder agenda items. "assignable" = applications whose current state is a `vote` state with `config.gremiumId` == meeting gremium.
- `attendance_service.py` — `AttendanceService`: roster = current gremium members (valid term window) + status upsert.
- `connection.py` — `LiveVoteConnection` WS handler: handshake auth (`resolve_ws_principal`), Origin/CSWSH check, token-bucket throttle, cast (distributed lock → `VotingService.cast`), broker fan-out pump, presence.
- `broker.py` — `MeetingBroker` protocol with `RedisBroker` (prod) and `InMemoryBroker` (tests/single-proc).
- `locks.py` — `Locker` protocol. `RedisLocker` (`SET NX PX` + Lua CAS release) or `InMemoryLocker`, key `vote:{id}:cast:{sub}`.
- `presence.py` — in-memory `PRESENCE` register of open voter connections (`viewers` event), single-replica scope.
- `publisher.py` — `MeetingPublisher` protocol + `NullPublisher` default (injected from app state in `create_app`).

**Domain / data model:**
- `meeting`: `gremium_id`(FK CASCADE), `title`, `date`, `start_time`/`end_time`, `status` IN `planned|live|closed` (CHECK, `closed` is terminal), `closed_at` (set once on close), `active_application_id`(FK SET NULL — beamer focus), `protokollant_id`(FK principal SET NULL — exactly one, required before going live), `created_by`.
- `meeting_attendance`: one row per `(meeting_id, principal_id)` (UNIQUE upsert). Columns: `status` IN `present|excused|absent`, `source` IN `self|lead`, `note`.
- `meeting_agenda_item`: agenda item = assigned `application_id` (nullable, NULL means a free-text agenda item that uses `title`), `body` (Markdown per agenda item, feeds the final protocol), `position` (ordered), `non_public` (redacted in public protocol PDF, numbering preserved). UNIQUE `(meeting_id, application_id)`.
- This module does not store votes. They live in `voting` (`Vote.meeting_id`/`agenda_item_id`). The service decorates `MeetingOut.votes` with `MeetingVoteOut` (counts/leading/voted/present/revealed/failedReason).
- `MeetingOut` carries computed RBAC flags: `canControl/canManage/canWrite/canManageVotes/canVote`, `isProtokollant`, plus `protocolId`, `gremiumName`, `protokollantName`.

**API surface:**
- `POST /api/meetings` — create (planned). Sends a meeting mail as a background task.
- `GET /api/meetings` / `GET /api/meetings/timeline` — list / keyset-paginated timeline (`direction=past|upcoming`, opaque `cursor`, fuzzy `q` collapses to one ranked list with offset cursor).
- `GET /api/meetings/gremien` — gremien filter (visibility-based, must precede `{meeting_id}`).
- `GET /api/meetings/{id}` — state. `PATCH /api/meetings/{id}` — control and planning, broadcasts `meeting_state`. `DELETE` — manager only.
- `GET /api/gremien/{gremium_id}/meeting-members` — protokollant candidates.
- `GET .../attendance`, `PUT .../attendance/me`, `PUT .../attendance/{principal_id}` — roster + status.
- `GET .../agenda`, `GET .../agenda/assignable`, `POST .../agenda`, `DELETE .../agenda/{item_id}`, `PUT .../agenda/order`, `PATCH .../agenda/{item_id}` (body/title/nonPublic).
- `POST .../votes` — create and open the decision vote of an agenda item. An application agenda item allows exactly one vote, a free-text agenda item allows many. `DELETE .../votes/{vote_id}` — delete a vote.
- `WS /api/ws/meetings/{id}` — voter channel (cast/subscribe). `WS /api/ws/meetings/{id}/beamer` — read-only, carries only `meeting_state|vote_opened|vote_tally|vote_closed`.

**Conventions & gotchas:**
- The server resolves RBAC from the session and scopes it per Gremium, never from the body (see [[admin-domain-rules]], [[sessions-protokollant-redesign]]). `canManage` = global `meeting.manage` OR per-Gremium `session.manage`. `canWrite` (status, agenda items, protocol) adds the assigned protokollant OR a role with `protocol.write`. `canManageVotes` adds `vote.manage`. `canVote` = admin OR `vote.cast` OR a voting delegation for this meeting. PATCH is field-gated: date, time and protokollant need `canManage`, status and activeApplication need `canWrite`.
- **Lifecycle invariants:** `planned→live` requires a protokollant, else 409. Only this transition creates the protocol, and the create is idempotent. It uses a local import of `ProtocolService` to avoid an import cycle. The API rejects votes and agenda item `body` edits before `live`. `closed` is terminal (no re-open), freezes date, time and protokollant, and sets `closed_at`. The protokollant cannot change after the protocol is final.
- **Vote secrecy / aggregate-only:** beamer and tally events carry only aggregates, never voter identities. While a `secret` vote is open, the tally hides `counts`/`leading` and shows only the participation `cast/eligible`. `VoteTallyEvent.from_vote` is the single enforcement point. Always build tallies through it.
- Votes on an application agenda item fail fast. The application must be in a `vote` state that matches `config.gremiumId` before the vote opens. Otherwise voters waste ballots on a vote that cannot close.
- **WS security:** the handshake authenticates from the session cookie. The CSRF middleware does NOT run on upgrades, so an explicit `Origin` allowlist guards against CSWSH. Close codes: `4401` (no session), `4403` (not eligible, after a `not_eligible` error frame), `4404`. A per-(meeting,sub) connection cap (`_MAX_CONNECTIONS_PER_PRINCIPAL=5`) and a per-connection token-bucket throttle (`rate_limited`) apply.
- The distributed lock `vote:{id}:cast:{sub}` serializes casting per voter (`:proxy` suffix for delegation casts). The real guarantee is the DB UNIQUE on `(vote_id, voter)`, so the lock is defense in depth. An own cast and a delegation cast are two separate casts (`asDelegation`).
- Presence (`viewers`) and the connection cap live in memory per process. That is a documented single-replica limit. Only the broker (Redis) fans out across instances.
- The broker and the locker come from `app.state`, with in-memory fallbacks for tests. Both are `Protocol`s, so you override them via `dependency_overrides`.

**Related:** be-voting, be-protocol, be-delegations, be-admin, be-auth, be-audit
