---
id: "000443"
title: An Event lists its decisions
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/applications
  - backend/app/modules/voting
---

# An Event lists its decisions

An Event must list the valid decisions of its linked Anträge and the closed votes of its
linked TOPs and votes. Each row must show the date, the meeting, the result, the approved
amount and the conditions. The newest row must be first. A row that the viewer cannot read
follows the rule for a link without access.

Reason: The decisions about an Event are in different meetings. The Gremium must find them in
one place.

Test: A backend unit test lists a decision of a linked Antrag and the vote of a linked TOP.
