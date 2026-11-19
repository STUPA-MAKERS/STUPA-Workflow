---
id: "001611"
title: A vote that approves stores the approved amount
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A vote that approves stores the approved amount

When a vote passes and its `pass` transition leads into a state with the flag `Bewilligt`, the
decision must hold an approved amount. It is the amount of the vote proposal (000132), else the
requested amount at the close of the vote. The value must be stored, never left empty.

Reason: The approved amount of an Antrag must not depend on whether a person or a vote approved it.

Test: A backend integration test closes a passed vote without a proposal and checks the stored amount.
