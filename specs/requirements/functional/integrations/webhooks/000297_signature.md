---
id: "000297"
title: A webhook request is signed with a timestamp
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/webhooks
---

# A webhook request is signed with a timestamp

The HMAC signature covers `"{timestamp}.{body}"`.

Reason: The timestamp in the signature blocks a replay.
