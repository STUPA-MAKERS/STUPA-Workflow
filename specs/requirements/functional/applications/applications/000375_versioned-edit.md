---
id: "000375"
title: An edit is versioned and audited without values
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications
scope:
  - backend/app/modules/applications
---

# An edit is versioned and audited without values

Every edit must write a new version and an `application_update` audit entry with the changed
field keys, never the values. Two edits on the same version must give 409, never 500.
