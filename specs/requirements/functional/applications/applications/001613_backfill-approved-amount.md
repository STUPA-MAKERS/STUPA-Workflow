---
id: "001613"
title: Existing approvals get their approved amount
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# Existing approvals get their approved amount

A migration must set the approved amount of every Antrag in a state with the flag `Bewilligt`
that has no approved amount. The value is the requested amount. The migration must write a
decision row for each such Antrag, with no conditions, so that the decision history has a
start.

Reason: After 001610 and 001611 every approval holds an amount. Old approvals must not look different from new ones.

Test: A migration test runs the migration on an approved Antrag without a decision and checks the decision row.
