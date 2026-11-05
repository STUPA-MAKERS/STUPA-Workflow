---
id: "000375"
title: An edit is versioned and audited without values
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/applications
---

# An edit is versioned and audited without values

Every edit writes a new version and an `application_update` audit entry with the changed field
keys, never the values. Two edits on the same version give 409, never 500.
