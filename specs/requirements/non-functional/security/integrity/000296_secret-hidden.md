---
id: "000296"
title: A webhook secret is never shown
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
---

# A webhook secret is never shown

The server must make the webhook secret with 32 random bytes. No response and no log must show
it.
