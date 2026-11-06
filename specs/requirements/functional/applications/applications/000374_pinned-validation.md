---
id: "000374"
title: Antrag data is checked against its pinned form
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/applications
  - backend/app/modules/forms
---

# Antrag data is checked against its pinned form

Create and edit must check the data against the pinned form version before any database write.
The server must keep only known field keys and must drop every other key.
