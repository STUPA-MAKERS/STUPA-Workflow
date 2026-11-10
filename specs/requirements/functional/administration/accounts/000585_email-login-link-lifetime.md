---
id: "000585"
title: An e-mail login link works once for 30 minutes
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# An e-mail login link works once for 30 minutes

A login link for an address must work once. It must stop working 30 minutes after the request.
A new request must not end an older link that is still valid.

Reason: The link opens every Antrag of the address, so a forwarded or old mail must not open them
later. A request must not end other links, because anybody who knows the address can request one
(`F/administration/accounts/000268`).

Test: `backend/tests/unit/test_email_login.py`: a second redeem and a redeem after 30 minutes
give 410.
