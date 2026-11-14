---
id: "000912"
title: An election for one seat can need the majority of the members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - backend/app/shared
  - backend/app/modules/livevote
  - frontend/src/app/features/meetings
---

# An election for one seat can need the majority of the members

An election for one seat must be able to have the rule `members_majority`. A candidate must
then be elected only with more votes than half of the eligible count. If no candidate reaches
this number, the result must be `no_majority`.

Reason: The Organisationssatzung asks for the "Mehrheit der Mitglieder" for the Vorsitz and the
other members of the AStA.

Test: A unit test of the election outcome with the rule `members_majority`.
