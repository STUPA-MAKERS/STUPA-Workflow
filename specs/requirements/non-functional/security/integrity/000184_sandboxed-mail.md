---
id: "000184"
title: Mail templates run sandboxed
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/notifications/templating.py
scope:
  - backend/app/modules/notifications
---

# Mail templates run sandboxed

A mail template must render in the sandboxed Jinja2 environment.
