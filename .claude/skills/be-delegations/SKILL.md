---
name: be-delegations
description: Session-bound vote/representation delegations (MeetingDelegation) + per-Gremium substitute pool (DelegationSubstitute), with vote-transfer gating, no-chain rules, lead-time deadlines, and the voting_delegation_check used by the voting module. Use when working on delegations, Vertretung, Stellvertreter pools, vote transfer/blocking, or routes under /api/delegations in backend/app/modules/delegations.
---

# Delegations / Vertretung — `backend/app/modules/delegations`

**Does:** Lets a voting member of a Gremium delegate access to one specific *meeting* to another principal, optionally transferring their vote (exclusive transfer, not a duplicate). Maintains a per-Gremium substitute (Stellvertreter) pool whose members can receive delegations without a lead-time deadline.

**Key files:**
- `models.py` — `MeetingDelegation` (one outgoing delegation per meeting+delegator) and `DelegationSubstitute` (pool entries).
- `schemas.py` — camelCase DTOs (`DelegationCreate/Out`, `SubstituteCreate/Out`, `MeetingDelegationContext`, `RecipientOut`, `VoteDelegationStatus`).
- `service.py` — `DelegationService` (security core: gates, eligibility, chain prevention, deadlines, audit) + module-level `voting_delegation_check` and `meeting_start_utc`.
- `router.py` — `/delegations` router (mounted at `/api/delegations` via `main.py`); self-service + admin views; auto-mails delegate on grant/revoke.
- `__init__.py` — module overview (legacy T-45 model context).

**Domain / data model:**
- `MeetingDelegation` (`meeting_delegation`): `meeting_id`, `gremium_id` (denormalized = `meeting.gremium_id`, avoids join in hot vote-cast path), `delegator_principal_id`, `delegate_principal_id`, `delegate_voting` (bool, transfers the vote), `via_pool` (bool, legitimated via pool → no lead deadline), `created_by` (actor `sub`), `created_at`. Constraints: unique `(meeting_id, delegator)`; partial unique `(meeting_id, delegate)` WHERE `delegate_voting` (at most one vote-transfer received per meeting).
- `DelegationSubstitute` (`delegation_substitute`): `gremium_id`, `member_principal_id` (NULL = gremium-wide substitute for *any* member), `substitute_principal_id`, `created_by`. Unique `(gremium, member, substitute)` + partial unique `(gremium, substitute)` WHERE `member IS NULL`.
- Config gates live on **`Gremium`** (`admin/models.py`): `allow_vote_delegation`, `delegation_lead_minutes`, `delegation_allow_external`; and on **`Settings`**: `delegation_voting_enabled` (global vote-transfer switch), `local_timezone`.
- Audit actions (`audit/actions.py`): `DELEGATION_GRANT`, `DELEGATION_REVOKE`, `DELEGATION_USE`, `DELEGATION_SUBSTITUTE_ADD`, `DELEGATION_SUBSTITUTE_REMOVE`.

**API surface:** (prefix `/api/delegations`)
- `GET /api/delegations?meetingId=` — own incoming+outgoing delegations; admins (`admin.delegations`) see all.
- `POST /api/delegations` — create session delegation (`{meetingId, delegateId, delegateVoting}`); mails the delegate.
- `DELETE /api/delegations/{id}` — revoke (hard delete, instant); delegator until meeting start, admin always; mails the delegate.
- `GET /api/delegations/meetings/{meeting_id}/context` — full dialog state: gates, deadline, my/incoming delegations, recipients.
- `GET /api/delegations/meetings/{meeting_id}/recipients?q=` — typeahead recipient list (members, pool, external if enabled).
- `GET /api/delegations/votes/{vote_id}/status` — caller's per-vote banner (`blocked` / `exercising`).
- `GET|POST /api/delegations/substitutes` , `DELETE /api/delegations/substitutes/{id}` — manage the per-Gremium pool.

**Conventions & gotchas:**
- **Session-bound, not blanket:** a delegation always targets one meeting; gremium + validity derive from the meeting. The old blanket-period model (`role_assignment.delegated_by`, T-45) is superseded; legacy rows still count for the RBAC resolver but **never** for voting.
- **Vote transfer is exclusive, not a duplicate:** `delegate_voting=True` blocks the delegator's own ballot for that meeting; the delegate may cast an *additional* ballot that runs under the delegator's `sub`. Enforcement lives in `voting_delegation_check(session, sub, meeting_id, eligible_group, now) -> (blocked, delegator_sub)`, consumed by `voting/service.py`. Votes without a `meeting_id` ignore delegations entirely; `eligible_group` must equal `str(gremium_id)`.
- **Eligibility:** only an *independently* vote-eligible member of the meeting's gremium may delegate — `_independently_eligible` checks Gremium-role with `vote.cast`, direct `role_assignment` (gremium-scoped, non-delegated), or OIDC group / `group_mapping` (mirrors the RBAC resolver, see `be-auth`).
- **No chains:** per meeting a principal is either delegator XOR delegate, never both, and you can't delegate to someone who already delegated their own vote. Create path serializes per meeting with a transaction-bound `pg_advisory_xact_lock` (key `_CREATE_LOCK_KEY` + meeting-hash arg) so concurrent read-then-insert can't form a chain.
- **Deadlines:** non-pool delegations until `meeting_start − delegation_lead_minutes`; pool delegations until meeting start; both only while meeting is `planned`. Meetings without a date are status-gated only (`meeting_start_utc` returns None). Times are tz-aware UTC; meeting date/time are stored naive in `settings.local_timezone`.
- **PII guard (#sec-audit):** `_assert_can_view_gremium` gates context/recipients/substitute-list — only `admin` role, `admin.delegations`, `meeting.manage`/`meeting.view_all`, gremium members, pool members, or gremium-`session.manage` holders may see roster/pool names; else 403. External typeahead escapes LIKE metacharacters (`_escape_like`).
- **Two permission tiers:** `admin.delegations` = full cross-gremium view/manage; `session.manage` (gremium-role) = manage that gremium's substitute pool only.
- Errors are RFC-9457 `ProblemDetail`; statuses follow the create docstring (403 gate/recipient/eligibility, 404 meeting/principal, 409 duplicate, 422 window/chain/self). Related memory: [[delegation-rework]].

**Related:** be-voting, be-livevote, be-auth, be-admin, be-audit, be-notifications
