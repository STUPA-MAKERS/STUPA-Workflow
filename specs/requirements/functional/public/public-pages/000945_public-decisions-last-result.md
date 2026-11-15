---
id: "000945"
title: The public decisions show the last result of a TOP
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/protocol/public_decisions.py
scope:
  - backend/app/modules/protocol
---

# The public decisions show the last result of a TOP

When a TOP has more than one closed vote with the same question, the list of public decisions
(000926) must show only the vote that closed last. This rule must apply to the rounds of an
election too. Votes with different questions on one TOP must each show.

Reason: Two rows for one motion with different results read as a contradiction to a person
who was not in the Sitzung.

Test: A backend unit test reads the public decisions of a TOP with a repeated vote and finds
one row with the last result.
