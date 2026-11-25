---
id: "003092"
title: An admin connects one Mollie account
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# An admin connects one Mollie account

The admin page `Mollie` (`/admin/mollie`) must hold an access token of one Mollie organization
with only read rights for the payments, refunds, chargebacks and settlements. The page must have
a button that tests the connection and shows the result and the name of the organization. The
page must need the permission `admin.mollie` (`Mollie verwalten`). Each save must write an audit
entry without the token.

Reason: The money of a shop arrives in Mollie and goes from there to the bank. One read-only
token gives the platform the data to assign the money, and no right to move it.

Test: A backend unit test saves a connection without the permission and expects 403, and tests
a connection against a fake Mollie.
