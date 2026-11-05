---
id: "000182"
title: The webhook SSRF guard runs at send time
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/webhooks
---

# The webhook SSRF guard runs at send time

The worker resolves all A and AAAA records before each send. One non-public address blocks the
delivery. The request goes to the checked IP address, follows no redirect and reads at most
64 KiB of the answer.

Reason: A check at configuration time does not stop DNS rebinding.
