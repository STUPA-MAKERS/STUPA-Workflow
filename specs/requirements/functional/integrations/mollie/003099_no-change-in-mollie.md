---
id: "003099"
title: The platform changes nothing in Mollie
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/mollie/client.py
scope:
  - backend/app/
  - frontend/src/app/
---
# The platform changes nothing in Mollie

The client must only read from Mollie. It must not create, change, refund or cancel a payment,
and must not change a setting of the account.

Reason: A wrong call can move money. A read-only client cannot, also with a stolen token.

Test: A unit test of the client expects only GET calls.
