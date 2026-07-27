---
name: delegation-rework
description: "Delegation is meeting-bound, never a blanket time range. Each Gremium keeps a substitute pool. Built in the worktree delegation-feature-audit (2026-06-11, uncommitted)"
metadata: 
  node_type: memory
  type: project
---

Complete rebuild of the delegation feature (spec of 2026-06-11, user decisions taken with the
question tool):

- **Meeting-bound, never a blanket time range**: the `meeting_delegation` table (migration 0014)
  replaces `role_assignment.delegated_by`. The old rows no longer count toward the voting right.
  Exactly 1 outgoing delegation per meeting and member. No chains. At most 1 vote delegation per
  recipient and meeting. A transfer is not a duplicate.
- **Deadline**: a member can set up a delegation until the meeting start minus
  `gremium.delegation_lead_minutes`. The lead time is configurable per Gremium in the admin Gremien
  dialog. A member can revoke until the meeting starts.
- **Substitute pool** (`delegation_substitute`, maintained in the Gremium member administration,
  permission admin.roles or the Gremium `session.manage`): elected Fachschaft representatives,
  including non-members. A member can delegate to the pool without any lead time, up to the meeting
  start. `member_principal_id NULL` makes the substitute cover the whole Gremium. An external
  recipient outside the pool works only when `gremium.delegation_allow_external` is set.
- **Entry points**: a card and a dialog on the meeting page (follower view and right column), a
  dashboard card, and the admin overview `/admin/delegations` (now with an admin home tile, list
  and revoke only). Voting UI: the banner "Stimmrecht an X delegiert" and the badge "In Vertretung"
  (endpoint `/delegations/votes/{id}/status`).
- External representatives: WebSocket and list access run through `is_participant` and the
  delegated meeting ids. The frontend routes `meetings/:id` and `voting/vote/:id` use
  `allowAuthenticated`, and the server stays authoritative. `delegation_voting_enabled` (global,
  default false) still applies. New: `settings.local_timezone` (Europe/Berlin) for the deadline
  computation.

Status: **merged into main (13d5a89, fast-forward, 2026-06-11)**. All tests, lint and typing are
green (backend 1371, frontend 561). Nothing is pushed. Migration 0014 is not rolled out.

**Warning, collision:** the unmerged branch `feat/backlog-audit-mail-pwa-perms` (checked out in the
main checkout) carries its OWN migrations 0014-0016 (drop_pii, notification_preferences,
granular_permissions), all with a down_revision chain from 0013. A merge therefore creates two
Alembic heads and a number clash with 0014_meeting_delegations. The backlog branch must renumber
to 0015-0017 with down_revision 0014_meeting_delegations before the merge. Other expected
conflicts: translations.ts, tests/test_livevote_service.py (the duplicate `get` fix exists on both
branches), and the "delegations" notification mails (#4-3), which may still reference the old
delegation model. See [[backlog-2026-06-11]] and [[admin-domain-rules]].
