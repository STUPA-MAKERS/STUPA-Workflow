---
id: "000271"
title: The logout ends the SSO session
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth/router.py
  - backend/app/modules/auth/oidc.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# The logout ends the SSO session

The logout must end the local session and must return the logout URL of the IdP, if the IdP has
one.
