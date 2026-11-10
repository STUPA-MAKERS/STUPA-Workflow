---
id: "000584"
title: An account address gets the applicant view only
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
---

# An account address gets the applicant view only

A login link must also be made for an address that a platform account holds, in any state. The
session of the link must be an applicant session only: it must not get the roles, the
permissions, the Gremien or the pages of the account. The answer must stay the same 202 for
every address (`NF/security/access/000278`).

Reason: A person with an account can still look at the own Anträge by mail. The account login
stays the SSO, so the mail login must not skip the SSO, its groups or a deactivation.

Test: `backend/tests/unit/test_email_login.py`: a link for the address of an active, a
deactivated and a merged account opens an applicant session that gets 401 on an account route.
