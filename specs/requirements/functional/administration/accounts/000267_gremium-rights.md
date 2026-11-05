---
id: "000267"
title: Gremium rights come only from the membership
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/admin
---

# Gremium rights come only from the membership

A gremium right comes only from the gremium membership. A global role or a raw OIDC claim
never grants a gremium right.
