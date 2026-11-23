---
id: "002714"
title: All Bereiche share one sequence of ticket numbers
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# All Bereiche share one sequence of ticket numbers

A ticket must get its number from one sequence for the whole platform, in the form `T-0001`. A
move to a different Bereich must not change the number.

Reason: The number is the reference in mails and in the subject of a mail (002734), so it must
point to one ticket for all time.

Test: A unit test creates tickets in two Bereiche and expects numbers in sequence.
