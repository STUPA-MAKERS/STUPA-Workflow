---
id: "000271"
title: The logout ends the SSO session
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# The logout ends the SSO session

The logout ends the local session and returns the logout URL of the IdP, if the IdP has one.
