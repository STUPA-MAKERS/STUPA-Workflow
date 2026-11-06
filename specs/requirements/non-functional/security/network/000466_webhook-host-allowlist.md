---
id: "000466"
title: Webhook targets can be limited to a host list
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/webhooks
  - backend/app/settings.py
---

# Webhook targets can be limited to a host list

When `webhook_host_allowlist` is set, a delivery to any other host must end as `dead`. The SSRF
guard must still apply.
