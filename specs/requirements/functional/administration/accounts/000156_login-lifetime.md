---
id: "000156"
title: Login lifetime is an admin setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/auth
  - backend/app/modules/admin
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# Login lifetime is an admin setting

A login must last `web_session_days` in a browser tab (default 90) and `pwa_session_days` in
the installed app (default 180). Each successful check at the IdP must move the end to now plus
this lifetime.
