---
id: "001852"
title: The message goes to the active members
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/notifications
---

# The message goes to the active members

A message must go to each active member of the Gremium that has an account with an e-mail
address, the sender included. A former member and a person in the substitute pool only must not
get it. The mail must name the Gremium and the sender, and its Reply-To must be the address of
the sender. The answer of a send must tell the number of recipients only, never their
addresses.

Reason: The members answer the sender, not the platform. The sender sees in the own copy what
the members got.

Test: A backend test of the recipient set, of the Reply-To header and of the answer.
