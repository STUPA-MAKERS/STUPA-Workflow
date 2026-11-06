---
id: "000473"
title: A permission check never reads principal.roles
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth/principal.py
scope:
  - backend/app/
---

# A permission check never reads principal.roles

A permission check must call `principal.has()` or `scope_allows()`. It must never test `"admin"
in principal.roles`.

Reason: A role test skips the scope cap of a token.
