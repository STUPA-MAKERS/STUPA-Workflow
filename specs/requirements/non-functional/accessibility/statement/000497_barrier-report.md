---
id: "000497"
title: A user can report a barrier as a ticket
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation: null
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
  - backend/app/modules/tickets
---

# A user can report a barrier as a ticket

The help ticket form must have the kind `barrier`. The form must work without a login. The
statement page must link to this form.

Reason: The law requires a feedback route. The help tickets already give one, so a new
channel is not necessary.
