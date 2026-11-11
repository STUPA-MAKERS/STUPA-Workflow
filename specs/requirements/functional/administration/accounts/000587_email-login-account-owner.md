---
id: "000587"
title: A confirmed guest Antrag of an account address belongs to the account
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/applications/email_login.py
  - backend/app/modules/applications/magic_link.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# A confirmed guest Antrag of an account address belongs to the account

When the e-mail of a guest Antrag is confirmed and an active account holds the address, compared
case-insensitively, the Antrag must belong to that account, as a capture does
(`F/applications/applications/000124`). Before the confirmation the Antrag must not belong to
the account. The audit entry must have `matchedByEmail`.

Reason: Anybody can type an address into the public form. Only the confirmation proves that the
mailbox owner filed the Antrag, so only then may it show up in the account.

Test: `backend/tests/integration/modules/auth/test_email_login.py`: a guest Antrag of an account address belongs to
nobody before the redeem and to the account after it.
