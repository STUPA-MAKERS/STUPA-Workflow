---
name: be-livevote
description: Meetings/Sitzungen — planned→live→closed lifecycle, agenda items (TOPs, Tagesordnung), attendance roster, and live voting over WebSocket (voter channel + read-only beamer stream), with the protocol created at meeting start. Use when working on meetings, agenda/TOPs, attendance, live-vote casting/tally, the meeting:{id} pub/sub channel, or MeetingService in backend/app/modules/livevote.
---

# Live-Vote / Meetings — `backend/app/modules/livevote`

**Does:** Manages Gremium meetings (Sitzungen): CRUD + lifecycle control, agenda items (TOPs), attendance, and a Redis-pub/sub live-vote channel with a voter WebSocket (cast/subscribe) and a read-only beamer stream. Second-largest backend module; the protocol is created lazily when a meeting goes live.

**Key files:**
- `models.py` — `Meeting`, `MeetingAttendance`, `MeetingAgendaItem` ORM tables.
- `schemas.py` — Pydantic API I/O (`MeetingCreate/Patch/Out`, `MeetingVoteOut`, `MeetingPage`, agenda + attendance bodies); camelCase aliases, `populate_by_name`.
- `events.py` — WS message contract (single source): server→client `meeting_state|vote_opened|vote_tally|vote_closed|vote_cancelled|viewers|error`, client→server `cast|subscribe`. `VoteTallyEvent.from_vote` enforces the "counts only at close" secrecy rule.
- `router.py` — REST routes + the two WS endpoints; per-(meeting,principal) connection cap; field-level RBAC gating; on `planned→live` creates the protocol.
- `service.py` — `MeetingService` (lifecycle, timeline, RBAC, vote decoration) + `BrokerPublisher` (builds WS events from voting schemas; implements the leaf `MeetingPublisher` protocol so `voting` does not import `livevote`). `meeting_channel(id)` → `meeting:{id}`.
- `agenda_service.py` — `AgendaService`: assign/remove/reorder TOPs, "assignable" = applications whose current state is a `vote` state with `config.gremiumId` == meeting gremium.
- `attendance_service.py` — `AttendanceService`: roster = current gremium members (valid term window) + status upsert.
- `connection.py` — `LiveVoteConnection` WS handler: handshake auth (`resolve_ws_principal`), Origin/CSWSH check, token-bucket throttle, cast (distributed lock → `VotingService.cast`), broker fan-out pump, presence.
- `broker.py` — `MeetingBroker` protocol with `RedisBroker` (prod) and `InMemoryBroker` (tests/single-proc).
- `locks.py` — `Locker` protocol; `RedisLocker` (`SET NX PX` + Lua CAS release) / `InMemoryLocker`, key `vote:{id}:cast:{sub}`.
- `presence.py` — in-memory `PRESENCE` register of open voter connections (`viewers` event); single-replica scope.
- `publisher.py` — `MeetingPublisher` protocol + `NullPublisher` default (injected from app state in `create_app`).

**Domain / data model:**
- `meeting`: `gremium_id`(FK CASCADE), `title`, `date`, `start_time`/`end_time`, `status` IN `planned|live|closed` (CHECK; `closed` terminal), `closed_at` (set once on close), `active_application_id`(FK SET NULL — beamer focus), `protokollant_id`(FK principal SET NULL — exactly one, required before going live), `created_by`.
- `meeting_attendance`: one row per `(meeting_id, principal_id)` (UNIQUE upsert); `status` IN `present|excused|absent`, `source` IN `self|lead`, `note`.
- `meeting_agenda_item`: TOP = assigned `application_id`(nullable; NULL ⇒ free-text TOP using `title`), `body` (per-TOP Markdown → final protocol), `position` (ordered), `non_public` (redacted in public protocol PDF, numbering preserved). UNIQUE `(meeting_id, application_id)`.
- Votes are not stored here — they live in `voting` (`Vote.meeting_id`/`agenda_item_id`); the service decorates `MeetingOut.votes` (`MeetingVoteOut`: counts/leading/voted/present/revealed/failedReason).
- `MeetingOut` carries computed RBAC flags: `canControl/canManage/canWrite/canManageVotes/canVote`, `isProtokollant`, plus `protocolId`, `gremiumName`, `protokollantName`.

**API surface:**
- `POST /api/meetings` — create (planned); sends a meeting mail (background task).
- `GET /api/meetings` / `GET /api/meetings/timeline` — list / keyset-paginated timeline (`direction=past|upcoming`, opaque `cursor`, fuzzy `q` collapses to one ranked list with offset cursor).
- `GET /api/meetings/gremien` — gremien filter (visibility-based, must precede `{meeting_id}`).
- `GET /api/meetings/{id}` — state; `PATCH /api/meetings/{id}` — control/planning → `meeting_state` broadcast; `DELETE` — manager only.
- `GET /api/gremien/{gremium_id}/meeting-members` — protokollant candidates.
- `GET .../attendance`, `PUT .../attendance/me`, `PUT .../attendance/{principal_id}` — roster + status.
- `GET .../agenda`, `GET .../agenda/assignable`, `POST .../agenda`, `DELETE .../agenda/{item_id}`, `PUT .../agenda/order`, `PATCH .../agenda/{item_id}` (body/title/nonPublic).
- `POST .../votes` — create+open a TOP's decision vote (application TOP = exactly one; free-text TOP = many); `DELETE .../votes/{vote_id}`.
- `WS /api/ws/meetings/{id}` — voter channel (cast/subscribe); `WS /api/ws/meetings/{id}/beamer` — read-only, only `meeting_state|vote_opened|vote_tally|vote_closed`.

**Conventions & gotchas:**
- RBAC is gremium-scoped and resolved server-side from the session, never the body (see [[admin-domain-rules]], [[sessions-protokollant-redesign]]). `canManage` = global `meeting.manage` OR per-gremium `session.manage`; `canWrite` (status/TOPs/protocol) adds the assigned protokollant OR a role with `protocol.write`; `canManageVotes` adds `vote.manage`; `canVote` = admin OR `vote.cast` OR a voting delegation for this meeting. PATCH is field-gated: date/time/protokollant need `canManage`, status/activeApplication need `canWrite`.
- **Lifecycle invariants:** `planned→live` requires a protokollant (else 409) and creates the protocol (only here, idempotent, via local import of `ProtocolService` to avoid a cycle); votes and TOP `body` minutes are rejected before `live`; `closed` is terminal (no re-open), freezes date/time/protokollant, sets `closed_at`; protokollant cannot change after the protocol is finalized.
- **Vote secrecy / aggregate-only:** beamer + tally events carry only aggregates, never voter identities. While a `secret` vote is open the tally hides `counts`/`leading` (only participation `cast/eligible`); `VoteTallyEvent.from_vote` is the single enforcement point — construct tallies through it.
- Application-TOP votes fail-fast: the app must be in a `vote` state (matching `config.gremiumId`) before opening, else cast ballots would be wasted on an unclosable vote.
- **WS security:** handshake authenticates from the session cookie (CSRF middleware does NOT run on upgrades → explicit `Origin` allowlist / CSWSH guard); close codes `4401`(no session)/`4403`(not eligible, after a `not_eligible` error frame)/`4404`. Per-(meeting,sub) connection cap (`_MAX_CONNECTIONS_PER_PRINCIPAL=5`) + per-connection token-bucket throttle (`rate_limited`).
- Casting is serialized per voter via the distributed lock `vote:{id}:cast:{sub}` (`:proxy` suffix for delegation casts); the real guarantee is the DB UNIQUE on `(vote_id, voter)` — the lock is defense-in-depth. Own vs. delegation are two separate casts (`asDelegation`).
- Presence (`viewers`) and the connection cap are in-memory/per-process (documented single-replica limit); only the broker (Redis) fans out across instances.
- Broker/locker come from `app.state` with in-memory fallbacks for tests; both are `Protocol`s — override via `dependency_overrides`.

**Related:** be-voting, be-protocol, be-delegations, be-admin, be-auth, be-audit
