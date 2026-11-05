---
id: "000153"
title: Mail templates are sandboxed
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/notifications
---

# Mail templates are sandboxed

Mail templates render in the sandboxed Jinja2 environment with camelCase placeholders.
