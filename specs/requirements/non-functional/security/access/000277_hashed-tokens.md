---
id: "000277"
title: Tokens are stored only as hashes
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth/tokens.py
  - backend/app/modules/auth/oauth.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# Tokens are stored only as hashes

The server must store a magic-link token as HMAC-SHA256 with a pepper and an OAuth code or
token as SHA-256. Every compare must be constant-time.
