---
name: sessions-protokollant-redesign
description: "Meeting/Protokollant redesign — per-meeting protokollant, granular gremium-role perms (incl Vote), generic agenda-item votes, 3-pane meeting view, member follow + beamer. Adjusts meetings/dashboard/tasks/applications to the landed flow engine."
metadata: 
  node_type: memory
  type: project
---

Meetings redesign, branch feat/admin-ux-flow-editor-fixes (2026-06-09). The user confirmed all design decisions with the question tool. It adjusts tasks, meetings, applications and dashboard to the landed flow engine ([[flow-engine-redesign]]).

## Confirmed decisions (question tool)
- Forced gremium roles → **vorstand, manager, member** (schriftfuehrung dropped). The migration reassigns existing schriftfuehrung memberships → **manager**.
- vorstand/manager (or any role with session.manage) create and edit meetings and assign ONE Protokollant. The assigned Protokollant runs the live meeting and writes the protocol. A manager may self-assign.
- Per-Gremium-role granular permission flags: **session.manage, vote.manage, vote.cast, protocol.write** (= GREMIUM_PERMISSIONS).
- **Keep immediate fire** on vote close. This OVERRIDES the spec line "once finalized transitions trigger". Finalize does the PDF and the send only. An application-agenda-item vote close fires the pass/fail branch at once, as the flow engine already does.

## Backend (all in backend/app/modules)
- **admin/gremium_roles.py**: GREMIUM_PERMISSIONS catalog. FORCED_GREMIUM_ROLES carries the default perms (vorstand/manager=all, member=[vote.cast]). Helpers `active_gremium_roles` / `gremium_ids_with_permission` / `gremium_member_ids` / `_time_valid_clause`. LEAD_ROLE_KEYS REMOVED. `_sanitize_perms` whitelists. admin/models.py GremiumRole.permissions JSONB, admin/schemas GremiumRole{Out,Create,Update}.permissions.
- **livevote/service/ MeetingService**: per-meeting flags can_manage(session.manage|global meeting.manage)/can_write(manage|protokollant|protocol.write)/can_manage_votes(manage|protokollant|vote.manage)/can_vote(admin|vote.cast)/is_member. `_emit` builds MeetingOut (no re-fetch in create/patch). `vote_eligible_count` (roster=members with vote.cast). `agenda_item_has_vote`. Meeting.protokollant_id FK principal.
- **livevote/schemas MeetingOut**: protokollantId/protokollantName + canManage/canWrite/canManageVotes/canVote (canControl kept = canWrite, master FE flag). MeetingVoteOut + agendaItemId + options. MeetingCreate/Patch + protokollantId. MeetingVoteOpenBody now takes **agendaItemId** (not applicationId), options default [yes,no,abstain].
- **livevote/router**: create/patch/agenda/attendance/votes endpoints switched ManagerDep→ReaderDep + service flag checks (per Gremium, not global meeting.manage). The WS voter channel is gated on is_member (members follow live). The beamer channel STAYS on meeting.manage. open_meeting_vote takes agendaItemId. An application agenda item rejects a 2nd vote (ConflictError), a generic agenda item takes many.
- **voting**: Vote.application_id NULLABLE + Vote.agenda_item_id FK. create() app_id optional + agenda_item_id. close() fires the branch ONLY when application_id is present (generic votes = no flow). VoteOut/_to_out + agendaItemId (defensive getattr). events.VoteOpenedEvent applicationId optional + agendaItemId/question.
- **auth/rbac.resolve_principal**: appends gremium_ids where an active membership-role grants vote.cast to Principal.groups (so in_group(gremium_id) == vote-eligible → gates the role's Vote perm at cast). This query runs LAST (the fake_session of the rbac unit tests returns empty when exhausted → no test change needed).
- **protocol/service**: finalize assembles the markdown from the agenda item bodies + their vote snippets (`_assemble_from_agenda`), and falls back to protocol.markdown when there are no agenda items. _vote_title handles the generic case (question).
- **migration 0040_sessions_rework**: adds gremium_role.permissions JSONB. It seeds a manager role per gremium with the default perms. It reassigns schriftfuehrung memberships→manager and deletes schriftfuehrung. It adds meeting.protokollant_id. It makes vote.application_id nullable and adds vote.agenda_item_id.
- Note (added later): the migration chain was squashed into `0001_baseline.py` after this redesign landed. The numbers 0033, 0040 and 0041 below now belong to unrelated FinTS migrations. Read this section as a historical record of the change, not as a current migration index.

## Frontend
- models/mappers/api-client: MeetingVote{applicationId nullable, agendaItemId, options}. Meeting{protokollantId, protokollantName, canManage/canWrite/canManageVotes/canVote}. MeetingCreate/PatchBody + protokollantId. openMeetingVote body agendaItemId. ws-messages VoteOpenedMsg + agendaItemId/question/optional applicationId.
- **meetings.component**: per-meeting flag gating (canManage/canWrite/canManageVotes/canVote computed from meeting()). showForbidden only on the list route. Protokollant-assign card (select from the attendance roster). Per-agenda-item decision questions and votes in the center editor. An application agenda item takes one vote + a question dialog. A generic agenda item takes many, added via the "+ Beschlussfrage" button. The bottom danger zone holds finalize with a confirm dialog. The **member follow view** (isFollower) shows read-only agenda item bodies + open votes with cast. The **beamer toggle** is a display mode on the member's own connection — current question + live results, the last one persists. WS vote_opened adds unseen votes for followers. Methods cast()/voteOptionsFor()/renderBody()/beamerVote().
- **dashboard**: big meeting shortcuts (live first, then planned, top 4) → /meetings/:id (a member inspects the planned agenda items through the meeting route).
- **gremium-roles page**: permission checkboxes (GREMIUM_PERMISSIONS) in the add/edit dialog + a permissions column. admin-api create/updateGremiumRole carry permissions + saveGremiumRolePermissions.
- i18n de+en: meetings.protokollant.*/beamer.*/follow.*/finalizeConfirm.*/vote.{untitled,addQuestion,count}, dashboard.sessions.*, admin.gremiumRoles.permissions + admin.gremiumPerm.<key>.
- Cleanup: the stale /applications/{id}/approval mock handler is gone. The "normal|vote|approval|decision" comments now read "normal|vote".

## Verification
- Backend: 92 affected tests green (.env aside per the altcha gotcha). The full unit suite gives 1360 pass / 1 PRE-EXISTING fail (test_pdf_router forbidden — _FakeSession lacks .scalar in the access.py creator-fallback, NOT ours) + integration DB-gated errors (no Postgres).
- FE: meetings/dashboard/gremium-roles/mappers(mapMeeting) specs green. 2 PRE-EXISTING FE fails, both unrelated: mappers mapApplication budgetId, and an a11y flow-editor listWebhooks mock gap.
- The user must run migration 0040 + rebuild. NOTE: the protokollant assignment hard-validates that the target is an active Gremium member (not that it holds protocol.write). The FE dropdown sources from the attendance roster.

## Round 2 (layout feedback + freetext bug)
- **Free-text agenda item add was failing**: dev DB drift. An early `create_all` created `meeting_agenda_item` with `application_id` NOT NULL and NO `title` column. The "table exists → skip" guard of migration 0033 never reconciled it. **migration 0041_agenda_freetext_fix** (idempotent inspector): ADD title + DROP NOT NULL on application_id. The user MUST run `alembic upgrade head` (we could not auto-apply it — the classifier blocked DDL on the shared dev DB).
- **Layout**: the meetings detail is now a real 3-col page shell — left sidebar agenda items (add/reorder/remove), center body (markdown per agenda item + decision questions + finalize danger), right sidebar attendance. Toolbar ABOVE the body with icon-buttons: meeting live/close (power/check icons, canControl), settings (edit icon → dialog), delete (delete icon), beamer toggle. The standalone protokollant/plan cards are gone, and the status moved to the toolbar. Loose votes (no agendaItemId) stay in a "Sitzungssteuerung" (meeting control) card below the shell (legacy + spec).
- **Combined settings dialog** (top-level): protokollant select (roster via listAttendance) + date + time, one PATCH. The user opens it from the toolbar edit-icon AND from the list-row edit-icon. **Delete**: toolbar icon + list-row icon + confirm dialog. New backend **DELETE /meetings/{id}** (MeetingService.delete, can_manage, cascades protocol/agenda/attendance, votes SET NULL) + FE api.deleteMeeting. The list actions column is now 9rem wide.
- i18n added: meetings.settings.title, meetings.delete.{title,body,confirm}, meetings.attendance.empty, meetings.toast.{settingsSaved,deleted}.
- Icons available: sun moon language edit delete add remove members roles user chevron-down power filter check (used power=open-meeting, check=close-meeting, edit=settings, delete=delete).

## Round 3 (2026-06-14) — Protokollant-only manager view (committed 3f916bd, pushed)
- Requirement: **only the assigned Protokollant gets the edit/manager view**. Everyone else (managers and chairs included) gets the live read-only and vote-only follower view.
- FE-only gating. RBAC stays server-authoritative, and the backend still grants the Protokollant canWrite so that saves work. The auth.service gained a new `userId` computed (= principal `sub`). In meetings.component: `isProtokollant` (meeting().protokollantId === userId), `isFollower` now = `m.protokollantId ? !isProtokollant() : (!canWrite && !canManage)`. The fallback keeps the old gate while NO Protokollant is assigned. A freshly created meeting is then not a detail dead-end, because the assignment happens from the overview list-edit or create dialog. `isFollower` is the single template switch (live block vs manager block).
- spec: fakeAuth gained `userId` (default 'pr-1') and a setup `userId` opt. We added a test for the non-protokollant → live view case. NOTE pre-existing red in the meetings spec on main: 3 tests (create-meeting redirect, create-protocol-on-demand, protokollant-PATCH) fail because of an unflushed `/api/gremien/{id}/meeting-members` — NOT from this change.

See [[flow-engine-redesign]], [[antragsplattform-backlog]], [[admin-domain-rules]].
