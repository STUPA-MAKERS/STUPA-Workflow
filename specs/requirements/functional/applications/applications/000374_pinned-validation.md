---
id: "000374"
title: Antrag data is checked against its pinned form
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/applications
  - backend/app/modules/forms
---

# Antrag data is checked against its pinned form

Create and edit check the data against the pinned form version before any database write. The
server keeps only known field keys and drops every other key.
