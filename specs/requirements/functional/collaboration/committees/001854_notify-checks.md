---
id: "001854"
title: A members message is checked and audited
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/audit
  - frontend/src/app/features/gremien
---

# A members message is checked and audited

The subject must hold 1 to 200 characters and the message 1 to 10000 characters, else the send
must fail with 422. The message must be plain text, and the mail must turn links in it into
links. Each send must write one audit entry `gremium_notify` with the Gremium, the subject and
the number of recipients, without addresses and without the message text. The dialog must ask
for no confirmation, and must show a toast with the number of recipients after the send.

Reason: The audit log shows who wrote to the members, and does not copy personal data or the
text into the hash chain.

Test: A backend test of the 422 limits and of the audit entry.
