---
id: "000585"
title: A login link works once and ends after a fixed time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/auth/email_login.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# A login link works once and ends after a fixed time

A login link must work once. A link from the login page must stop working 30 minutes after the
request. A link in the mail after a new Antrag must stop working when the confirmation window
of the Antrag ends (`confirm_ttl_hours`). A new request must not end an older link that is
still valid.

Reason: The link opens every Antrag of the address, so a forwarded or old mail must not open them
later. A request must not end other links, because anybody who knows the address can request one
(`F/administration/accounts/000268`).

Test: `backend/tests/integration/modules/auth/test_email_login.py`: a second redeem and a redeem after the end give
410.
