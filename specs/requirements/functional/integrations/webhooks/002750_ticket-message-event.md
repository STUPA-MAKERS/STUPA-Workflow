---
id: "002750"
title: A message of the sender is a webhook event
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/webhooks
  - backend/app/modules/tickets
---

# A message of the sender is a webhook event

The event `ticket.message` must occur for each message of the sender on a ticket, from the app
and from a mail. It must not occur for a message of the team and not for the first message of
a new ticket. Its payload fields must include the number, the title, the Bereich, the link and
the text of the message. The event must carry the Gremium of the Bereich (002749).

Reason: A team that works in a chat must see an answer of a sender there. The first message is
in `ticket.created`, and a second event for it would report one mail two times.

Test: A unit test adds one sender message and one team message to a ticket and expects one
delivery.
