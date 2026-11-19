---
id: "001612"
title: List, detail and export show the requested and the approved amount
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# List, detail and export show the requested and the approved amount

The Antrag list, the Antrag detail and the export `export.xlsx` must show the requested amount
(`Beantragt`, `Requested`) and the approved amount (`Genehmigt`, `Approved`). The approved amount
must be empty for an Antrag that is not in a state with the flag `Bewilligt`.

Reason: A reviewer must see at a glance whether a decision changed the amount.

Test: A backend unit test checks both columns in the export. A frontend unit test checks both values in the list row and in the detail.
