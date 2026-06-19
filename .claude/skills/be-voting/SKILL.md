---
name: be-voting
description: Standalone vote lifecycle (Vote/Ballot/SecretBallot/VotedMarker) — quorum (count/percent), majorities (simple/absolute/two_thirds), tieBreak, secret ballots with identity split from choice, gremium-scoped tally reads, and pass/fail flow-branch firing on close. CRITICAL module. Use when working on votes, ballots, quorum, majority rules, tally, or secret voting in backend/app/modules/voting.
---

# Voting — `backend/app/modules/voting`

**Does:** Runs the full lifecycle of a vote attached to an application (and optionally a meeting/agenda-item): create → open → cast → close. On close it tallies, applies quorum + majority + tie-break, persists the result, and fires the application flow's `pass`/`fail` branch.

**Key files:**
- `models.py` — SQLAlchemy tables `Vote`, `Ballot`, `VotedMarker`, `SecretBallot`; status/result CHECK constraints; unique-per-voter constraints.
- `tally.py` — pure, side-effect-free counting + outcome logic (`tally`, `leading`, `result`, `failed_reason`, `Outcome`); the majority/quorum math. Fully unit-testable, no DB/time.
- `service.py` — `VotingService`: lifecycle methods, race-safe casting via DB constraints, reveal/scope rules, flow-branch firing on close.
- `schemas.py` — Pydantic IO (`VoteCreate`, `BallotIn`, `TallyOut`, `VoteOut`, `BallotAccepted`, `VoteClosed`); camelCase aliases.
- `router.py` — FastAPI routes; RBAC gates (`vote.manage`, `vote.cast`); problem+json error responses.
- `VoteConfig`/`Quorum` live in `app/shared/config_schemas.py`, stored as JSONB in `vote.config`.

**Domain / data model:**
- **Vote** (`vote`): `application_id` (nullable — NULL = generic free-text-TOP resolution question, fires NO flow branch), `meeting_id` (SET NULL on meeting delete), `agenda_item_id` (CASCADE), `eligible_group` (group key: OIDC group or gremium-UUID-as-text, the denominator/membership scope), `question`, `config` (JSONB = `VoteConfig`), `eligible_count` (authoritative roster size = percent-quorum denominator; NULL ⇒ percent quorum fail-closed), `opens_state_id`, `opens_at`, `closes_at`, `status`, `result`, `result_branch_transition_id`.
- **status** enum: `draft` → `open` → `closed`, plus `cancelled` (abort while open; no result, no branch). **result** enum: `passed` | `rejected` | `tie` (nullable until closed).
- **Ballot** (`ballot`): open vote = one row per voter; `UNIQUE(vote_id, voter_sub)` enforces single vote atomically; `choice` nullable.
- **VotedMarker** (`voted_marker`): secret path — `UNIQUE(vote_id, voter_sub)` records "has voted", the identity anchor, no choice.
- **SecretBallot** (`secret_ballot`): secret path — only `choice`, no identity, **deliberately timestamp-free** (a precise `at` would be a correlation channel back to the voter). Identity (VotedMarker) is split from choice (SecretBallot) so `choice` is never traceable to a voter.
- **VoteConfig**: `options` (≥2, unique), `majorityRule` (`simple`/`absolute`/`two_thirds`), `quorum` (`{type: count|percent, value}` or null), `abstainCountsQuorum` (default true), `secret` (default false), `allowChange` (default true), `tieBreak` (`passed`/`rejected`/`tie`, default `rejected`).
- **Options convention** (`tally.py`): `yes` = approve, `no` = reject, `abstain` = abstention. Abstain never counts toward majority; counts toward quorum only if `abstainCountsQuorum`. Extra n-options count as cast/quorum participation but not toward the yes/no majority.

**Majority math** (`_majority`, integer arithmetic; percent quorum uses `Decimal`):
- `simple` — yes > no; tie at yes == no.
- `absolute` — `2·yes > cast`; tie at `2·yes == cast`.
- `two_thirds` — `≥ ⅔` (statute/association law, R5.1): `3·yes ≥ 2·(yes+no)` passes (exact ⅔ passes); symmetric for no; neither side reaching ⅔ (blocking minority) ⇒ raw tie.
- Raw tie resolved by `tieBreak`. **Quorum failure ⇒ `rejected`, fail-closed**, independent of majority.

**API surface:**
- `POST /api/applications/{application_id}/votes` — `vote.manage`; create vote (draft).
- `POST /api/votes/{vote_id}/open` — `vote.manage`; draft→open; broadcasts `vote_opened` if meeting-bound. 409 if not draft.
- `POST /api/votes/{vote_id}/close` — `vote.manage`; tally → result → fire `pass`/`fail` branch atomically; broadcasts `vote_closed`. 409 if quorum unmet (unless window expired via Cron `now`), or if no matching branch transition.
- `POST /api/votes/{vote_id}/cancel` — `vote.manage`; open→cancelled; no result/branch.
- `POST /api/votes/{vote_id}/ballot` — auth only at gate; service enforces `vote.cast`+group (own vote) or delegation row (`asDelegation`); broadcasts `vote_tally`. 403/409/422.
- `GET /api/votes/{vote_id}` — read; vote state + tally (secret ⇒ only counts, never voters); scoped to the vote's read circle.

**Conventions & gotchas:**
- **Race safety (CRITICAL):** casting is serialized on DB constraints, NOT app logic. Open: `INSERT … ON CONFLICT (vote_id, voter_sub)` — `allowChange` ⇒ `DO UPDATE` (and `xmax = 0` in RETURNING distinguishes `cast` from `changed`), else `DO NOTHING` + empty RETURNING ⇒ 409. Secret: `voted_marker` insert is the gate; `allowChange` has NO effect (anonymous, unlinkable) ⇒ second cast 409.
- `cast` and `close`/`cancel` lock the `vote` row with `SELECT … FOR UPDATE` so a last-second ballot can't land after the tally but before `status=closed`.
- **Close is atomic with the flow transition:** `flow.fire_branch` commits the staged vote changes together with the `voteResult` transition + status_event. If `fire` fails (guard/race), the whole tx rolls back → vote stays `open` and retryable rather than "closed but branch never fired" (stuck). Application-bound vote with no matching `pass`/`fail` branch ⇒ 409 (misconfigured flow), fail-closed.
- **Quorum / stuck-vote:** manual close (`now=None`) with unmet quorum ⇒ 409 (collect more ballots or cancel). Cron passing `now` with an expired `closes_at` window force-closes as terminal quorum-missed → fires `fail` branch (otherwise the application hangs forever in the `vote` state).
- **eligible_count is set from the roster**, never derived from logged-in users (that would be fail-open). Percent quorum without it is rejected at create (`VoteCreate` validator) and fail-closed unmet in `tally`.
- **Reveal rule** (`open_tally_revealed` + `_tally_out`): running `counts`/`leading` are hidden until `revealed` = closed, OR (not secret AND all expected ballots in). `expected` = present attendees + absent-delegator proxy votes (so `voted` can't overshoot `present` and leak early). Secret open votes are never revealed pre-close; only `voted`/`present` travel. Session-less open non-secret votes reveal immediately.
- **Scope (`assert_can_read` / `get_scoped`):** `GET /votes/{id}` is fail-closed object-level authz — admin bypass; meeting-bound votes follow meeting visibility (see `be-livevote` `MeetingService.assert_can_read`); session-less votes need `vote.manage`/`application.read`/`application.read_all`. Prevents cross-tenant tally reads (incl. closed secret votes). `service.get()` is the UNSCOPED internal reuse path (tally broadcast) — don't expose it directly.
- **Delegation** (`asDelegation`): own vote and proxy vote are two separate ballots under different `voter_sub`; each protected by its own unique constraint. `voting_delegation_check` (see `be-delegations`) decides `blocked` (own right delegated away) vs `delegator_sub`. Proxy use writes a `DELEGATION_USE` audit row (`be-audit`); rolled back with the tx on a later 409.
- Live-vote broadcasts (`vote_opened`/`vote_closed`/`vote_cancelled`/`vote_tally`) go through the meeting publisher — no-op without a meeting. See `be-livevote`.
- No `eval` anywhere; flow branch resolution is whitelist-based via `FlowService.branch_transition`. See [[conventions]] for tz-aware timestamps, RFC-9457 problem+json, server-side RBAC.

**Related:** be-flow, be-livevote, be-delegations, be-audit, be-applications, conventions
