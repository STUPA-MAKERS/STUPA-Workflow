---
id: "000267"
title: Gremium rights come only from the membership
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/admin
---

# Gremium rights come only from the membership

A gremium right must come only from the gremium membership. A global role or a raw OIDC claim
must never grant a gremium right.
