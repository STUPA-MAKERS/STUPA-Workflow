---
id: "000826"
title: An accepted vote of the Gremium passes its step
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-16
replaced_by: F/finance/budget/000838
scope:
  - backend/app/modules/budget
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# An accepted vote of the Gremium passes its step

A step that names a Gremium must take the vote of a meeting of that Gremium on the plan
version (000838). The platform must record the step as passed when the vote is accepted.
The step must keep the link to the vote. A vote that is not accepted must send the version
back to the draft: each step that the version passed must be open again. A vote must
decide only the next step of its version: the close of a vote must change nothing in the
plan, and must not fail, when the version went back to draft, when the step is already
passed or when the fiscal year is closed.

Reason: The decision of the body is the vote, so the plan must not need a second entry
by hand. The close of a vote belongs to the Gremium and must not depend on the state of
the plan.

Test: The backend tests close an accepted and a refused vote of a step and a vote of a step that
is no longer the next one.
