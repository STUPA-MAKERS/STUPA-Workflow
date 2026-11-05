---
id: "000226"
title: A change request starts as a spec
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - specs/
---

# A change request starts as a spec

1. Write every change request as a new spec or as a change to a spec first.
2. Give the spec to the owner for review.
3. Start the implementation only after the owner approves the spec.
4. If the owner asks for changes, change the spec and give it for review again.

Reason: The owner approves what the code must do before work starts. The approved spec is then
the measure for the review of the code.

Test: Review. A pull request with code names the approved spec that it implements.
