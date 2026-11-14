---
id: "000906"
title: A new Gremium starts with the meeting defaults
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/admin
  - backend/app/modules/meetings
  - backend/app/modules/gremien
  - frontend/src/app/pages/admin
---

# A new Gremium starts with the meeting defaults

The meeting settings must hold the defaults `quorumPercent` 40, `repeatQuorumPercent` 25,
`guestsMayVote` off, `allowVoteDelegation` off, `delegationLeadMinutes` 120 and
`delegationMaxPerDelegate` 2. The form of a new Gremium must start with these values. A change
of a default must not change a Gremium that exists.

Reason: The numbers come from the Satzungen, and an admin must be able to follow a change of a
Satzung without a release.

Test: An integration test that changes a default and reads an old Gremium.
