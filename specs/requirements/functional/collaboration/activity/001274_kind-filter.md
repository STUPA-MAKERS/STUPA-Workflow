---
id: "001274"
title: The activity page filters by the kind of item
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
implementation: null
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# The activity page filters by the kind of item

The page must have one filter chip "Art" with a multiple choice of the kinds of item: Anträge,
To-Dos, Tickets and Sitzungen. A kind whose feature is off must not be a choice. No kind
selected must show all kinds. The chip must not show a count (000207).

Reason: A person who looks for the answer on an Antrag does not read through card moves.
