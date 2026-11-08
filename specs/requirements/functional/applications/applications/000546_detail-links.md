---
id: "000546"
title: The detail shows Vorgänger and Folgeanträge
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The detail shows Vorgänger and Folgeanträge

The detail of an Antrag must show its Vorgänger and its Folgeanträge as rows that open the
linked Antrag. A row must show only when the reader can open the linked Antrag. The applicant
view must follow the same rule.

Reason: The reader sees the history of a recurring Antrag in one place. A hidden row keeps the
title of an Antrag away from a reader without access.

Test: Unit tests of the detail read: a link to an Antrag outside the read scope is not in the
result. A frontend test checks both rows and the navigation.
