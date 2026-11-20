---
id: "001852"
title: The message goes to the members and the substitute pool
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation: null
scope:
  - backend/app/modules/gremien_overview
  - backend/app/modules/notifications
---

# The message goes to the members and the substitute pool

A message must go to each member of the Gremium and to each person in its substitute pool that
has an active account with an e-mail address, the sender included. A person who is a member and
in the pool must get one mail. A former member must not get it. The mail must name the Gremium
and the sender, and its Reply-To must be the address of the sender. The answer of a send must
tell the number of recipients only, never their addresses.

Reason: The pool persons stand in for the members, so they need the same information. The
members answer the sender, not the platform. The sender sees in the own copy what the members
got.

Test: A backend test of the recipient set, of the Reply-To header and of the answer.
