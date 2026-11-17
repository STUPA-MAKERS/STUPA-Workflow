---
id: "001277"
title: An activity row names the item, the actor, the change and the time
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-17
implementation: null
scope:
  - backend/app/modules/activity
  - frontend/src/app/pages/activity
---

# An activity row names the item, the actor, the change and the time

Each row must show the kind and the title of the item, the actor, a short text of the change
and the time. The row must open the detail page of the item. A comment or a note must show at
most its first line. A row must not show a value of a form field of an Antrag. An actor
without a name must show as "Ohne Namen" (000159), the platform itself as "System".

Reason: The row says enough to decide whether to open the item, without copying personal data
of an Antrag into a second view.
