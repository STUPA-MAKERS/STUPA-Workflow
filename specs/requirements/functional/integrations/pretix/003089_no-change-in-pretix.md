---
id: "003089"
title: The platform changes nothing in pretix
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/pretix/client.py
scope:
  - backend/app/
  - frontend/src/app/
---
# The platform changes nothing in pretix

The client must only read from pretix. It must not create, change or delete an event, a product, a quota, an order or a setting in pretix.

Reason: pretix is the system of the shop. A new shop and each change in it are the work of a
person in pretix, and a wrong change by the platform can lose money or tickets.

Test: A unit test of the client expects only GET calls.
