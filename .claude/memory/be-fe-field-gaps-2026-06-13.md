---
name: be-fe-field-gaps-2026-06-13
description: backlog
metadata: 
  node_type: memory
  type: reference
---

#5-4 audit (2026-06-13): backend schema fields that exist on the server but never reach the
Angular frontend. This is a read-only finding. Nothing changed yet. It belongs to
[[backlog-2026-06-13]].

## Whole features missing from the frontend (the biggest gaps)
- **GroupMapping** — there is no `/admin/group-mappings` page at all. The mapping from an OIDC
  group to a role (and a Gremium) is complete in the API (`admin/schemas.py:274-288`), but no UI
  can manage it. The audit log even links `group_mapping` to /admin/users, and that page holds no
  mapper.
- **MailTemplate** — there is no template editor and no preview anywhere.
  `subjectI18n`, `bodyI18n`, `bodyHtmlI18n` and `placeholders` plus the MailPreview DTOs
  (`notifications/schemas.py:27-49`) have no reference in the frontend. The notifications page
  edits only the task-reminder NotificationSettings.
- **ApplicationType.comparisonOffers** — the backend returns and accepts this config feature
  (`admin/schemas.py:162,173,182`, sub-model `config_schemas.py:354-358` with required, minCount,
  thresholdAmount and as), but there is no admin UI. The type editor handles only `nameI18n`,
  `gremiumId` and `hasBudget`.

## Editable gaps (the API accepts the value, the frontend offers no input)
- **MeetingVoteOpenBody.majorityRule / eligibleCount / quorumPercent**
  (`livevote/schemas.py:187,191,193`) — the open-live-vote dialog cannot set the majority rule or
  override the quorum, so both always fall back to the default.
- **FiscalYearUpdate.year / active** (`tree_schemas.py:139,140`) — there is no edit operation and
  no UI for a fiscal year at all. `FiscalYearCreate.active` is also not settable.
- **BudgetNode.active** (`tree_schemas.py:32,46`) — the UI cannot deactivate a cost center. This
  is also a display gap.
- **FormField FieldValidation.fileTypes / maxSizeMB / maxRows** (`config_schemas.py:92-94`) — the
  frontend model holds the file and table field validators, but the form editor offers no input.

## Display gaps (the backend returns the field, the frontend never shows it)
- Expense: `actor` (no "booked by" column), `accountName` (no account column), `transferId` (no
  transfer badge), see `tree_schemas.py:293-295`.
- Meetings and votes: `MeetingOut.closedAt`, `AgendaItemOut.stateLabel`,
  `AssignableApplicationOut.stateLabel`, `AttendanceOut.source`, `VoteOut.eligibleGroup`,
  `VoteOut.opensAt`, `VoteConfig.abstainCountsQuorum`, `VoteConfig.tieBreak`,
  `ProtocolOut.sentAt`.
- Applications: `StateOut.kind`, `TimelineEventOut.actor`, `ApplicationOut.lang` (minor).
- `FormVersionOut.version` — an admin cannot see which form version is open in the editor.

Totals: about 3 missing features, about 10 editable gaps and about 16 display gaps. Each fix adds
a feature or a UI element and needs its own design decision.
