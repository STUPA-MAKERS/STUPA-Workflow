---
id: "000273"
title: An agent never casts a ballot or merges accounts
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - mcp/
---

# An agent never casts a ballot or merges accounts

No token can get `vote.cast` or `admin.users.merge`. An agent can manage votes, but only a
person casts a ballot.
