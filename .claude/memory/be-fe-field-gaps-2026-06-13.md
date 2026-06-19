---
name: be-fe-field-gaps-2026-06-13
description: backlog
metadata: 
  node_type: memory
  type: reference
---

#5-4 audit (2026-06-13): backend schema fields that exist server-side but are NOT exposed in the Angular FE. Read-only finding; nothing changed yet. Part of [[backlog-2026-06-13]].

## Whole features missing from the FE (biggest)
- **GroupMapping** — no `/admin/group-mappings` page at all. OIDC-group→role(+gremium) mapping is API-complete (`admin/schemas.py:274-288`) but unmanageable in UI. Audit-log even links group_mapping → /admin/users (which has no mapper).
- **MailTemplate** — no template editor/preview anywhere. `subjectI18n/bodyI18n/bodyHtmlI18n/placeholders` + MailPreview DTOs (`notifications/schemas.py:27-49`) all unreferenced. Notifications page only edits the task-reminder NotificationSettings.
- **ApplicationType.comparisonOffers** — config feature (`admin/schemas.py:162,173,182`; sub-model `config_schemas.py:354-358` required/minCount/thresholdAmount/as) returned + accepted but no admin UI; type editor only does nameI18n/gremiumId/hasBudget.

## Editable gaps (API accepts, no FE input)
- **MeetingVoteOpenBody.majorityRule / eligibleCount / quorumPercent** (`livevote/schemas.py:187,191,193`) — open-live-vote dialog can't set majority rule or quorum override → always defaults.
- **FiscalYearUpdate.year / active** (`tree_schemas.py:139,140`) — no fiscal-year EDIT op/UI at all; FiscalYearCreate.active also not settable.
- **BudgetNode.active** (`tree_schemas.py:32,46`) — can't deactivate a cost centre from UI (also a display-gap).
- **FormField FieldValidation.fileTypes / maxSizeMB / maxRows** (`config_schemas.py:92-94`) — file/table field validators in FE model but no form-editor input.

## Display gaps (returned, never shown)
- Expense: `actor` (no "booked by" col), `accountName` (no account col), `transferId` (no transfer badge) — `tree_schemas.py:293-295`.
- Meetings/votes: `MeetingOut.closedAt`, `AgendaItemOut.stateLabel`, `AssignableApplicationOut.stateLabel`, `AttendanceOut.source`, `VoteOut.eligibleGroup`, `VoteOut.opensAt`, `VoteConfig.abstainCountsQuorum`, `VoteConfig.tieBreak`, `ProtocolOut.sentAt`.
- Applications: `StateOut.kind`, `TimelineEventOut.actor`, `ApplicationOut.lang` (minor).
- `FormVersionOut.version` (admin can't see which form version is being edited).

Totals ≈ 3 missing features, ~10 editable-gaps, ~16 display-gaps. Each fix = a feature/UI addition needing its own design decision.
