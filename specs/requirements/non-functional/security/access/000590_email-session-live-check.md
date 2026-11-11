---
id: "000590"
title: An e-mail session reads its Anträge at each request
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/auth/email_login.py
  - backend/app/deps.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# An e-mail session reads its Anträge at each request

An e-mail session must find its Anträge at each request from the applicant e-mail of the
Antrag. An anonymized Antrag must then drop out, and a new Antrag of the address must join.

Reason: A list fixed at the login would keep an Antrag open after its anonymization.

Test: `backend/tests/integration/modules/auth/test_email_login.py`: after an anonymization the session gets 403 for
that Antrag.
