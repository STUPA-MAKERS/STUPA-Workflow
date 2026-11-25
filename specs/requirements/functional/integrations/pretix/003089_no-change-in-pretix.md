---
id: "003089"
title: The platform changes nothing in pretix except a new shop
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The platform changes nothing in pretix except a new shop

The client must only read from pretix, except the copy of 003087. It must not change or delete
an event, a product, a quota, an order or a setting in pretix.

Reason: pretix is the system of the shop. A change in the shop is the work of a person in
pretix, and a wrong change by the platform can lose money or tickets.

Test: A unit test of the client expects only GET calls and the one clone call.
