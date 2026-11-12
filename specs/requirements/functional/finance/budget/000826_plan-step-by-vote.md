---
id: "000826"
title: An accepted vote of the Gremium passes its step
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
---

# An accepted vote of the Gremium passes its step

A step that names a Gremium must offer a vote of that Gremium on the plan version. The
platform must record the step as passed when the vote is accepted. The step must keep the
link to the vote. A refused vote must leave the step open.

Reason: The decision of the body is the vote, so the plan must not need a second entry
by hand.
