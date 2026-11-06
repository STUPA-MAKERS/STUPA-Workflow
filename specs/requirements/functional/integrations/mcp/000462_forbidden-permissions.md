---
id: "000462"
title: No agent token gets a human-only permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth/oauth.py
---

# No agent token gets a human-only permission

`FORBIDDEN_PERMISSIONS` must hold `vote.cast`, `backup.manage`, `admin.users.merge` and
`admin.users.revoke_groups`. No token must get one of them, whatever the scope or the admin
status says.

Reason: Each of them acts for a person or cannot be undone.
