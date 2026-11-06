---
id: "000265"
title: A deactivated or merged account cannot log in
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# A deactivated or merged account cannot log in

The login of a deactivated principal must fail. A login with the `sub` of a merged account must
fail: the OIDC callback must redirect to `/?loginError=account_merged`, and the start page must
say why. A merged account must not be activated again.
