---
id: "002853"
title: A Bestellung has a status of its status list
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/rules.py
  - backend/app/modules/orders/service.py
scope:
  - backend/app/modules/orders
---

# A Bestellung has a status of its status list

The status of a Bestellung must be one status of the list of the Bestellungen (003035). A person
must be able to set each status from each other status. The status must not say if an invoice
or a booking exists. A status can set the order date or the delivery date (003037).

Reason: The status tells where the goods are. The invoice and the booking are their own
elements, and a status that repeats them can contradict them. A wrong delivery report must be
easy to take back, and a date that a person typed is more exact than the day of the click.

Test: A backend unit test sets each status from each other status and refuses a key that is
not in the list.
