---
id: "000133"
title: A positions answer has label and offers
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/forms
  - frontend/src/app/pages/admin
---

# A positions answer has label and offers

An answer of a `positions` field ("Kostenaufstellung") is a list of positions. Each position
has a `label` and `offers`. Each offer has `label`, `value` (a finite number, at least 0) and
`preferred`. Exactly one offer of a position is preferred.
