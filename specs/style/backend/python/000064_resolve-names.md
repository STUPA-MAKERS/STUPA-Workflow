---
id: "000064"
title: Names are resolved on the server
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
---

# Names are resolved on the server

A response must not carry a raw UUID, principal id or `sub` for display. Resolve it to a name
in the serializer through `app/modules/auth/identity.py`. If no name exists, leave the field
empty or use a generic label.
