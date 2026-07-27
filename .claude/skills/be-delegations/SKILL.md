---
name: be-delegations
description: Meeting-bound vote and representation delegations (MeetingDelegation) plus a per-Gremium substitute pool (DelegationSubstitute). Covers vote-transfer gating, no-chain rules, lead-time deadlines, and the voting_delegation_check the voting module uses. Use when working on delegations, Vertretung, Stellvertreter pools, vote transfer/blocking, or routes under /api/delegations in backend/app/modules/delegations.
---

# Delegations — `backend/app/modules/delegations`

**Does:** Lets a voting member of a Gremium delegate access to one specific *meeting* to another principal. The delegator can also transfer the vote. That transfer is exclusive, not a duplicate. The module also keeps a per-Gremium substitute pool. A member of that pool can receive a delegation without a lead-time deadline.

**Key files:**
- `models.py` — `MeetingDelegation` (one outgoing delegation per meeting and delegator) and `DelegationSubstitute` (pool entries).
- `schemas.py` — camelCase DTOs (`DelegationCreate/Out`, `SubstituteCreate/Out`, `MeetingDelegationContext`, `RecipientOut`, `VoteDelegationStatus`).
- `service.py` — `DelegationService` (security core: gates, eligibility, chain prevention, deadlines, audit) + module-level `voting_delegation_check` and `meeting_start_utc`.
- `router.py` — the `/delegations` router, mounted at `/api/delegations` by `main.py`. It holds the self-service and the admin views. It mails the delegate on a grant and on a revoke.
- `__init__.py` — module overview (legacy T-45 model context).

**Domain / data model:**
- `MeetingDelegation` (`meeting_delegation`): `meeting_id`, `gremium_id` (denormalized = `meeting.gremium_id`, avoids a join in the hot vote-cast path), `delegator_principal_id`, `delegate_principal_id`, `delegate_voting` (bool, transfers the vote), `via_pool` (bool, legitimated through the pool → no lead deadline), `created_by` (actor `sub`), `created_at`. Constraints: unique `(meeting_id, delegator)`. A partial unique `(meeting_id, delegate)` WHERE `delegate_voting` allows at most one received vote transfer per meeting.
- `DelegationSubstitute` (`delegation_substitute`): `gremium_id`, `member_principal_id` (NULL = Gremium-wide substitute for *any* member), `substitute_principal_id`, `created_by`. Unique `(gremium, member, substitute)` + partial unique `(gremium, substitute)` WHERE `member IS NULL`.
- Config gates live on **`Gremium`** (`admin/models.py`): `allow_vote_delegation`, `delegation_lead_minutes`, `delegation_allow_external`. More gates live on **`Settings`**: `delegation_voting_enabled` (global vote-transfer switch) and `local_timezone`.
- Audit actions (`audit/actions.py`): `DELEGATION_GRANT`, `DELEGATION_REVOKE`, `DELEGATION_USE`, `DELEGATION_SUBSTITUTE_ADD`, `DELEGATION_SUBSTITUTE_REMOVE`.

**API surface:** (prefix `/api/delegations`)
- `GET /api/delegations?meetingId=` — the own incoming and outgoing delegations. An admin with `admin.delegations` sees all of them.
- `POST /api/delegations` — create a meeting delegation (`{meetingId, delegateId, delegateVoting}`). It mails the delegate.
- `DELETE /api/delegations/{id}` — revoke, a hard delete that applies at once. The delegator may revoke until the meeting starts, an admin always. It mails the delegate.
- `GET /api/delegations/meetings/{meeting_id}/context` — full dialog state: gates, deadline, my delegations, incoming delegations, recipients.
- `GET /api/delegations/meetings/{meeting_id}/recipients?q=` — typeahead recipient list (members, pool, external if enabled).
- `GET /api/delegations/votes/{vote_id}/status` — the per-vote banner of the caller (`blocked` / `exercising`).
- `GET|POST /api/delegations/substitutes` , `DELETE /api/delegations/substitutes/{id}` — manage the per-Gremium pool.

**Conventions & gotchas:**
- **Meeting-bound, not blanket:** a delegation always targets one meeting. The Gremium and the validity come from that meeting. The old blanket-period model (`role_assignment.delegated_by`, T-45) is superseded. Legacy rows still count for the RBAC resolver, but **never** for voting.
- **Vote transfer is exclusive, not a duplicate:** `delegate_voting=True` blocks the own ballot of the delegator for that meeting. The delegate may cast an *additional* ballot that runs under the `sub` of the delegator. `voting_delegation_check(session, sub, meeting_id, eligible_group, now) -> (blocked, delegator_sub)` enforces this, and `voting/service.py` calls it. A vote without a `meeting_id` ignores delegations. `eligible_group` must equal `str(gremium_id)`.
- **Eligibility:** only a member of the Gremium of the meeting who is *independently* vote-eligible may delegate. `_independently_eligible` checks a Gremium role with `vote.cast`, a direct `role_assignment` (Gremium-scoped, not delegated), or an OIDC group / `group_mapping`. This mirrors the RBAC resolver, see `be-auth`.
- **No chains:** per meeting a principal is either delegator or delegate, never both. You cannot delegate to a principal who already delegated their own vote. The create path serializes per meeting with a transaction-bound `pg_advisory_xact_lock` (key `_CREATE_LOCK_KEY` plus a meeting-hash argument). A concurrent read-then-insert can then not form a chain.
- **Deadlines:** a non-pool delegation runs until `meeting_start − delegation_lead_minutes`. A pool delegation runs until the meeting starts. Both work only while the meeting is `planned`. A meeting without a date has the status gate only (`meeting_start_utc` returns None). Times are tz-aware UTC. The meeting date and time are stored naive in `settings.local_timezone`.
- **PII guard (#sec-audit):** `_assert_can_view_gremium` gates the context, the recipients and the substitute list. Only these may see roster or pool names: the `admin` role, `admin.delegations`, `meeting.manage`/`meeting.view_all`, Gremium members, pool members, and `session.manage` holders for that Gremium. Everyone else gets 403. The external typeahead escapes LIKE metacharacters (`_escape_like`).
- **Two permission tiers:** `admin.delegations` gives the full cross-Gremium view and manage. `session.manage` (Gremium role) manages only the substitute pool of that Gremium.
- Errors are RFC-9457 `ProblemDetail`. The statuses follow the create docstring: 403 gate/recipient/eligibility, 404 meeting/principal, 409 duplicate, 422 window/chain/self. Related memory: [[delegation-rework]].

**Related:** be-voting, be-livevote, be-auth, be-admin, be-audit, be-notifications
