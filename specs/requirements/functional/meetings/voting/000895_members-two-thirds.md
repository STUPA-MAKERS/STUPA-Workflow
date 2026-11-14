---
id: "000895"
title: A vote can need two thirds of the members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-14
implementation: null
scope:
  - backend/app/modules/voting
  - backend/app/shared
---

# A vote can need two thirds of the members

The majority rule `members_two_thirds` must pass a motion only when the yes ballots are at
least two thirds of the eligible count. The check must be `3 * yes >= 2 * eligible`.

Reason: The Organisationssatzung asks for the "Zweidrittelmehrheit der Mitglieder" for its own
change and for the Abwahl of an AStA member.

Test: A unit test of `tally.result` with the rule `members_two_thirds`.
