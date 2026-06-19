---
name: sessions-protokollant-redesign
description: "Session/Protokollant redesign — per-meeting protokollant, granular gremium-role perms (incl Vote), generic-TOP votes, 3-pane session view, member follow + beamer. Adjusts meetings/dashboard/tasks/applications to the landed flow engine."
metadata: 
  node_type: memory
  type: project
---

Sessions redesign, branch feat/admin-ux-flow-editor-fixes (2026-06-09). All design decisions confirmed via question tool. Adjusts tasks/meetings/applications/dashboard to the landed flow engine ([[flow-engine-redesign]]).

## Confirmed decisions (question tool)
- Forced gremium roles → **vorstand, manager, member** (schriftfuehrung dropped). Migration reassigns existing schriftfuehrung memberships → **manager**.
- vorstand/manager (or any role w/ session.manage) create/edit meetings + assign ONE protokollant; the assigned protokollant runs the live session + writes; a manager may self-assign.
- Per-committee-role granular permission flags: **session.manage, vote.manage, vote.cast, protocol.write** (= GREMIUM_PERMISSIONS).
- **Keep immediate fire** on vote close (the spec's "once finalized transitions trigger" was OVERRIDDEN — finalize = PDF/send only; app-TOP vote close fires pass/fail branch immediately, as the flow engine already does).

## Backend (all in backend/app/modules)
- **admin/gremium_roles.py**: GREMIUM_PERMISSIONS catalog; FORCED_GREMIUM_ROLES carries default perms (vorstand/manager=all, member=[vote.cast]); helpers `active_gremium_roles` / `gremium_ids_with_permission` / `gremium_member_ids` / `_time_valid_clause`. LEAD_ROLE_KEYS REMOVED. `_sanitize_perms` whitelists. admin/models.py GremiumRole.permissions JSONB; admin/schemas GremiumRole{Out,Create,Update}.permissions.
- **livevote/service.py MeetingService**: per-meeting flags can_manage(session.manage|global meeting.manage)/can_write(manage|protokollant|protocol.write)/can_manage_votes(manage|protokollant|vote.manage)/can_vote(admin|vote.cast)/is_member; `_emit` builds MeetingOut (no re-fetch in create/patch); `vote_eligible_count` (roster=members w/ vote.cast); `agenda_item_has_vote`. Meeting.protokollant_id FK principal.
- **livevote/schemas MeetingOut**: protokollantId/protokollantName + canManage/canWrite/canManageVotes/canVote (canControl kept = canWrite, master FE flag). MeetingVoteOut + agendaItemId + options. MeetingCreate/Patch + protokollantId. MeetingVoteOpenBody now takes **agendaItemId** (not applicationId), options default [yes,no,abstain].
- **livevote/router**: create/patch/agenda/attendance/votes endpoints switched ManagerDep→ReaderDep + service flag checks (gremium-genau, not global meeting.manage). WS voter channel gated on is_member (members follow live); beamer channel STAYS meeting.manage. open_meeting_vote takes agendaItemId; app-TOP rejects 2nd vote (ConflictError); generic-TOP many.
- **voting**: Vote.application_id NULLABLE + Vote.agenda_item_id FK. create() app_id optional + agenda_item_id; close() fires branch ONLY when application_id present (generic votes = no flow). VoteOut/_to_out + agendaItemId (defensive getattr). events.VoteOpenedEvent applicationId optional + agendaItemId/question.
- **auth/rbac.resolve_principal**: appends gremium_ids where active membership-role grants vote.cast to Principal.groups (so in_group(gremium_id) == vote-eligible → gates the role's Vote perm at cast). Query is LAST execute (rbac unit tests' fake_session returns empty when exhausted → no test change needed).
- **protocol/service**: finalize assembles markdown from agenda TOP bodies + their vote snippets (`_assemble_from_agenda`), falls back to protocol.markdown if no TOPs. _vote_title handles generic (question).
- **migration 0040_sessions_rework**: gremium_role.permissions JSONB; seed manager role per gremium + default perms; reassign schriftfuehrung memberships→manager + delete schriftfuehrung; meeting.protokollant_id; vote.application_id nullable + vote.agenda_item_id.

## Frontend
- models/mappers/api-client: MeetingVote{applicationId nullable, agendaItemId, options}; Meeting{protokollantId, protokollantName, canManage/canWrite/canManageVotes/canVote}; MeetingCreate/PatchBody + protokollantId; openMeetingVote body agendaItemId; ws-messages VoteOpenedMsg + agendaItemId/question/optional applicationId.
- **meetings.component**: per-meeting flag gating (canManage/canWrite/canManageVotes/canVote computed from meeting()); showForbidden only on list route; protokollant-assign card (select from attendance roster); per-TOP decision questions/votes in center editor (app-TOP one + question dialog, generic-TOP many via "+ Beschlussfrage"); bottom danger finalize w/ confirm dialog; **member follow view** (isFollower: read-only TOP bodies + open votes w/ cast); **beamer toggle** (display mode on member's own connection — current question + live results, last persists); WS vote_opened adds unseen votes for followers; cast()/voteOptionsFor()/renderBody()/beamerVote().
- **dashboard**: big session shortcuts (live first then planned, top 4) → /meetings/:id (members inspect planned TOPs via the session route).
- **gremium-roles page**: permission checkboxes (GREMIUM_PERMISSIONS) in add/edit dialog + a permissions column; admin-api create/updateGremiumRole carry permissions + saveGremiumRolePermissions.
- i18n de+en: meetings.protokollant.*/beamer.*/follow.*/finalizeConfirm.*/vote.{untitled,addQuestion,count}; dashboard.sessions.*; admin.gremiumRoles.permissions + admin.gremiumPerm.<key>.
- Cleanup: stale /applications/{id}/approval mock handler gone; "normal|vote|approval|decision" comments → "normal|vote".

## Verification
- Backend: 92 affected tests green (.env aside per altcha gotcha); full unit suite 1360 pass / 1 PRE-EXISTING fail (test_pdf_router forbidden — _FakeSession lacks .scalar in access.py creator-fallback, NOT ours) + integration DB-gated errors (no Postgres).
- FE: meetings/dashboard/gremium-roles/mappers(mapMeeting) specs green. 2 PRE-EXISTING FE fails unrelated: mappers mapApplication budgetId; a11y flow-editor listWebhooks mock gap.
- User must run migration 0040 + rebuild. NOTE: protokollant assignment hard-validates target is active gremium member (not the protocol.write perm) — FE dropdown sources from attendance roster.

## Round 2 (layout feedback + freetext bug)
- **Freetext-TOP add was failing**: dev DB drift — `meeting_agenda_item` was created by an early `create_all` with `application_id` NOT NULL and NO `title` column; migration 0033's "table exists → skip" guard never reconciled it. **migration 0041_agenda_freetext_fix** (idempotent inspector): ADD title + DROP NOT NULL on application_id. User MUST run `alembic upgrade head` (couldn't auto-apply — classifier blocked DDL on shared dev DB).
- **Layout**: meetings detail now a real 3-col page shell — left sidebar TOPs (add/reorder/remove), center body (per-TOP markdown + decision questions + finalize danger), right sidebar attendance. Toolbar ABOVE body with icon-buttons: session live/close (power/check icons, canControl), settings (edit icon → dialog), delete (delete icon), beamer toggle. Standalone protokollant/plan cards removed; status moved to toolbar. Loose votes (no agendaItemId) kept in a "Sitzungssteuerung" card below shell (legacy + spec).
- **Combined settings dialog** (top-level): protokollant select (roster via listAttendance) + date + time, one PATCH. Opened from toolbar edit-icon AND from list-row edit-icon. **Delete**: toolbar icon + list-row icon + confirm dialog. New backend **DELETE /meetings/{id}** (MeetingService.delete, can_manage; cascades protocol/agenda/attendance, votes SET NULL) + FE api.deleteMeeting. List actions column widened to 9rem.
- i18n added: meetings.settings.title, meetings.delete.{title,body,confirm}, meetings.attendance.empty, meetings.toast.{settingsSaved,deleted}.
- Icons available: sun moon language edit delete add remove members roles user chevron-down power filter check (used power=open-session, check=close-session, edit=settings, delete=delete).

## Round 3 (2026-06-14) — Protokollant-only manager view (committed 3f916bd, pushed)
- Requirement: **only the assigned Protokollant gets the edit/manager view**; everyone else (incl. Verwalter/chairs) gets the live read-/vote-only follower view.
- FE-only gating (RBAC stays server-authoritative; backend still grants Protokollant canWrite so saves work). auth.service: new `userId` computed (= principal `sub`). meetings.component: `isProtokollant` (meeting().protokollantId === userId); `isFollower` now = `m.protokollantId ? !isProtokollant() : (!canWrite && !canManage)`. The fallback keeps the old gate while NO protokollant is assigned (so a freshly created meeting isn't a detail dead-end — assignment happens from the overview list-edit/create). `isFollower` is the single template switch (live block vs manager block).
- spec: fakeAuth gained `userId` (default 'pr-1'), setup `userId` opt; added test for the non-protokollant → live view case. NOTE pre-existing red in meetings spec on main: 3 tests (create-meeting redirect, create-protocol-on-demand, protokollant-PATCH) fail due to an unflushed `/api/gremien/{id}/meeting-members` — NOT from this change.

See [[flow-engine-redesign]], [[antragsplattform-backlog]], [[admin-domain-rules]].
