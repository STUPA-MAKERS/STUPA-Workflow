---
id: "000462"
title: No agent token gets a human-only permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/auth/oauth.py
scope:
  - backend/app/modules/auth/oauth.py
  - backend/app/modules/auth
  - backend/app/deps.py
  - mcp/
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# No agent token gets a human-only permission

`FORBIDDEN_PERMISSIONS` must hold `vote.cast`, `backup.manage`, `admin.users.merge` and
`admin.users.revoke_groups`. No token must get one of them, whatever the scope or the admin
status says. An agent can manage votes, but only a person must cast a ballot.

Reason: Each of them acts for a person or cannot be undone. The holder of `backup.manage` can
read and replace the whole database.
