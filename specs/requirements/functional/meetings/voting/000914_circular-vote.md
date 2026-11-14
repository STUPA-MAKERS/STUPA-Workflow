---
id: "000914"
title: A Gremium can decide by Umlaufverfahren
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# A Gremium can decide by Umlaufverfahren

A vote without a meeting must be able to have the kind "Umlaufverfahren" (`circular`). Such a
vote must be a motion with the rule `members_majority`. Its cast window must be at least
`circularMinDays` days (000917). It must take no ballot of a delegation and no guest ballot.

Reason: The Organisationssatzung and the Geschäftsordnung allow an urgent Beschluss outside a
Sitzung under these conditions.

Test: An integration test that creates a circular vote with a short window and gets 422.
