---
id: "000133"
title: A positions answer has label and offers
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
---

# A positions answer has label and offers

An answer of a `positions` field ("Kostenaufstellung") must be a list of positions. Each
position must have a `label` and `offers`. Each offer must have `label`, `value` (a finite
number, at least 0) and `preferred`. Exactly one offer of a position must be preferred.
