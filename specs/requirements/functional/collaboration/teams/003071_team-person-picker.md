---
id: "003071"
title: The picker offers teams and persons
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - frontend/src/app/features/gremien
  - backend/app/modules/todos
---

# The picker offers teams and persons

The picker for board entries and Termin invitations must offer teams and persons in one search
field. A sub-team hit must show the name of its parent team as subtitle. A hit of an inherent
team must show the image of the Gremium in the avatar slot. This replaces the Gremium hits of
001074.

Reason: One picker for both kinds, as today, now with teams.

Test: A frontend unit test searches the picker and gets a team hit and a person hit.
