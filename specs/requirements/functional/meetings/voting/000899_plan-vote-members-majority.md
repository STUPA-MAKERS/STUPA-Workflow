---
id: "000899"
title: The vote on a Haushaltsplan needs the majority of the members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - backend/app/modules/budget
---

# The vote on a Haushaltsplan needs the majority of the members

A vote on a Haushaltsplan or a Nachtrag (000838) must use the rule `members_majority`. The
server must set the rule, and the form must not offer a different rule.

Reason: The Organisationssatzung asks for the "Mehrheit der Mitglieder" for the Haushaltsplan
and its Nachträge.

Test: An integration test that creates the vote of a plan step.
