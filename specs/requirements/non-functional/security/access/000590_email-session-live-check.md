---
id: "000590"
title: An e-mail session checks the address at each request
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# An e-mail session checks the address at each request

An e-mail session must find its Anträge at each request from the applicant e-mail of the
Antrag. An anonymized Antrag must then drop out, and a new Antrag of the address must join. The
session must end when an account with the address exists
(`F/administration/accounts/000584`).

Reason: A list fixed at the login would keep an Antrag open after its anonymization and would keep
a session open after the person got an account.

Test: `backend/tests/unit/test_email_login.py`: after an anonymization the session gets 403 for
that Antrag, and after an account with the address appears the session gets 401.
