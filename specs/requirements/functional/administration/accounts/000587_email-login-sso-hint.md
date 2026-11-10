---
id: "000587"
title: An account address gets a hint to the SSO login
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# An account address gets a hint to the SSO login

A login request for the address of an active account must send a mail without a link to the
platform. The mail must tell that the account logs in through the SSO. The answer must stay the
same 202.

Reason: The person then learns why no link comes. Only the owner of the mailbox reads the hint, so
the answer still tells nothing about the address.

Test: `backend/tests/unit/test_email_login.py`: a request for an account address queues the hint
mail and no link.
