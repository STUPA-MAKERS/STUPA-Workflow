---
id: "000265"
title: A deactivated or merged account cannot log in
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# A deactivated or merged account cannot log in

The login of a deactivated principal fails. The login with the `sub` of a merged account
answers 403 `account_merged`, and the start page says why. A merged account cannot be
activated again.
