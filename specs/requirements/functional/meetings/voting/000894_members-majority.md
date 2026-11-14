---
id: "000894"
title: A vote can need the majority of the members
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - backend/app/shared
---

# A vote can need the majority of the members

The majority rule `members_majority` must pass a motion only when the yes ballots are more than
half of the eligible count. An abstention and a missing ballot must have the effect of a no
ballot.

Reason: The Organisationssatzung asks for the "Mehrheit der Mitglieder" for a Satzung, a
Haushaltsplan and the Beitrag.

Test: A unit test of `tally.result` with the rule `members_majority`.
