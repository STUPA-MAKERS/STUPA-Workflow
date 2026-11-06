---
id: "000182"
title: The webhook SSRF guard runs at send time
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/webhooks
---

# The webhook SSRF guard runs at send time

The worker must resolve all A and AAAA records before each send. One non-public address must
block the delivery. The request must go to the checked IP address, must follow no redirect and
must read at most 64 KiB of the answer.

Reason: A check at configuration time does not stop DNS rebinding.
