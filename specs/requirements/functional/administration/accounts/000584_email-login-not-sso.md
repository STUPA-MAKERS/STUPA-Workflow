---
id: "000584"
title: The e-mail login is only for an address without an account
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# The e-mail login is only for an address without an account

A login link must not be made for an address that a platform account holds, compared
case-insensitively. Every account counts, also a deactivated or a merged one. The answer must
stay the same 202 as for every other address (`NF/security/access/000278`).

Reason: A person with an account logs in through the SSO. A second login path by mail would skip
the SSO, its groups and a deactivation.

Test: `backend/tests/unit/test_email_login.py`: a request for the address of an active, a
deactivated and a merged account makes no link and answers 202.
