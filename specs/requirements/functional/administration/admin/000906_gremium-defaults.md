---
id: "000906"
title: A new Gremium starts with the meeting defaults
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/integration/modules/livevote/test_open_window.py:test_gremium_defaults_leave_an_old_gremium"
  - "backend/tests/unit/modules/livevote/test_open_window.py:test_update_gremium_defaults_audits_only_the_change"
implementation:
  - backend/app/modules/livevote/open_window.py
  - backend/app/modules/admin/router/settings_router.py
  - backend/app/modules/meetings/models.py
  - frontend/src/app/pages/admin/committees/gremium-defaults-dialog/gremium-defaults-dialog.component.ts
  - frontend/src/app/pages/admin/committees/gremium-dialog/gremium-dialog.component.ts
scope:
  - backend/app/modules/admin
  - backend/app/modules/meetings
  - backend/app/modules/gremien
  - frontend/src/app/pages/admin
---

# A new Gremium starts with the meeting defaults

The meeting settings must hold the defaults `quorumPercent` 40, `repeatQuorumPercent` 25,
`guestsMayVote` off, `allowVoteDelegation` off, `delegationLeadMinutes` 120,
`delegationMaxPerDelegate` 2 and `termStartMonth` 10 (000948). The form of a new Gremium must start with these values. A change
of a default must not change a Gremium that exists.

Reason: The numbers come from the Satzungen, and an admin must be able to follow a change of a
Satzung without a release.

Test: An integration test that changes a default and reads an old Gremium.
