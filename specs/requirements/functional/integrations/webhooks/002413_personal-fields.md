---
id: "002413"
title: A personal payload field is marked and off by default
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
protocols:
  - "P/integrations/webhooks/000963"
implementation:
  - backend/app/modules/webhooks/catalog.py
  - frontend/src/app/pages/admin/webhooks/webhooks.component.html
scope:
  - backend/app/modules/webhooks
  - frontend/src/app/pages/admin/webhooks
---

# A personal payload field is marked and off by default

A field that the field catalog marks as personal must show a "personenbezogen" mark in the
webhook dialog. A new event subscription must start with all personal fields off. An anonymized
or erased person must give `null` for a personal field.

Reason: Personal data leaves the platform only when an admin chooses it on purpose (DSGVO).

Test: A component test checks the mark and the default. A unit test anonymizes an Antrag and
checks that `applicantName` is `null`.
