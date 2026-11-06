---
id: "000296"
title: A webhook secret is never shown
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/admin
---

# A webhook secret is never shown

The server makes the webhook secret with 32 random bytes. No response and no log shows it.
