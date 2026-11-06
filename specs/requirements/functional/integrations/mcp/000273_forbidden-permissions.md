---
id: "000273"
title: An agent never casts a ballot or merges accounts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth/oauth.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - mcp/
---

# An agent never casts a ballot or merges accounts

No token must get `vote.cast` or `admin.users.merge`. An agent can manage votes, but only a
person must cast a ballot.
