---
id: "002874"
title: The invoice fills an empty real price
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
---

# The invoice fills an empty real price

When a Bestellung without a real price gets an invoice, the server must set the real price to
the gross amount of the invoice. It must do this only when the invoice belongs to no other
Bestellung. A person must be able to change the real price after that. The server must not
change a real price that is set.

Reason: The gross amount of the invoice is the real price in the usual case. On an invoice for
several purchases each Bestellung has only a part of the amount, so a person types it.

Test: A backend unit test links an invoice to one Bestellung and reads the gross amount, then
links it to a second Bestellung and reads no price there.
