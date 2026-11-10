---
id: "000586"
title: The e-mail login confirms the open guest Anträge of the address
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/auth/email_login.py
scope:
  - backend/app/modules/auth
  - backend/app/deps.py
  - backend/app/modules/applications
---

# The e-mail login confirms the open guest Anträge of the address

The first redeem of a login link must confirm the e-mail of every guest Antrag of the address
that waits for the confirmation. Each confirmed Antrag must then start its flow.

Reason: The login link proves that the person reads the mailbox, and that is what the
confirmation checks.

Test: `backend/tests/integration/modules/auth/test_email_login.py`: a redeem confirms two waiting Anträge and starts
their flows once.
