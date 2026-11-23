---
id: "002582"
title: The webhook dialog saves only with a name and a valid URL
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/src/app/pages/admin/webhooks/webhooks.component.spec.ts:WebhooksComponent"
implementation:
  - frontend/src/app/pages/admin/webhooks/webhooks.component.ts
  - frontend/src/app/pages/admin/webhooks/webhooks.component.html
scope:
  - frontend/src/app/pages/admin/webhooks
---

# The webhook dialog saves only with a name and a valid URL

The name field of the webhook dialog must be marked as required. The button "Speichern" must stay
off while the name is empty or the URL is not a valid http(s) URL.

Reason: The server refuses a webhook without a name (`WebhookCreate.name`, at least one
character). The dialog let the save run with an empty name, and the admin saw only
"Speichern fehlgeschlagen" without a cause.

Test: The tests of the webhook page check that the save stays off with a valid URL and no name,
and turns on when a name is typed.
