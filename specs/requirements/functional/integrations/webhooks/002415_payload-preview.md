---
id: "002415"
title: The webhook dialog shows a payload preview
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - frontend/src/app/pages/admin/webhooks/webhooks.component.ts
scope:
  - frontend/src/app/pages/admin/webhooks
---

# The webhook dialog shows a payload preview

The webhook dialog must show, for each subscribed event, an example body with the chosen fields
and example values. The preview must change when a field is turned on or off.

Reason: The admin sees what the receiver gets before the webhook is saved.

Test: A component test turns a field on and checks that the preview holds its key.
