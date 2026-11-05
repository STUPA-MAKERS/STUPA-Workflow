---
id: "000185"
title: The UI shows no raw IDs
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/
  - frontend/src/app/
---

# The UI shows no raw IDs

The UI must not show a UUID, a principal ID or a `sub`. The server resolves an ID to a name
through `app/modules/auth/identity.py`. If no name is found, the field is empty or shows a
generic label.

Reason: An ID means nothing to a user.
