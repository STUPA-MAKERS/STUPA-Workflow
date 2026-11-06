---
id: "000392"
title: Forwarded headers come only from the proxy
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - deploy/
  - backend/app/settings.py
scope:
  - deploy/
  - backend/app/settings.py
---

# Forwarded headers come only from the proxy

`FORWARDED_ALLOW_IPS` must be the exact IP address of the direct upstream, never a whole
private range or `*`.

Reason: A wider range lets an internal host fake `X-Forwarded-For`, which bypasses rate limits.

Test: Review. The settings validator refuses only `*` in production.
