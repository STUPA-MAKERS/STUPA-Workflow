---
id: "000539"
title: Archived Beschaffungen stay findable
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/search
---

# Archived Beschaffungen stay findable

The ⌘K search must have the source `Beschaffungen`. The source and the board filter
`Beschaffungen mit Archiv` must include archived Beschaffungen.

Reason: A person looks up an earlier purchase for the supplier and the price, and these cards are archived.

Test: A backend unit test finds an archived Beschaffung in the search.
