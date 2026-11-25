---
id: "002863"
title: A person who reads the Antrag reads its Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/router.py
scope:
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# A person who reads the Antrag reads its Bestellungen

A person must read a Bestellung when the person reads its Antrag. The server must answer 404 for
a Bestellung of an Antrag that the person does not read. A Bestellung without an Antrag (003014)
must be read by a person with the permission `order.manage` or `budget.view`, and the server
must answer 404 to every other person.

Reason: The Bestellungen are a part of the story of an Antrag. A second read rule would hide
them from the Gremium that decided the Antrag. Without an Antrag no Gremium owns the purchase,
so the persons who open the page "Bestellungen" read it.

Test: A backend integration test reads the Bestellungen as a member of the Gremium of the Antrag
and gets 404 as a person without the read of the Antrag. It reads a Bestellung without an
Antrag with `budget.view` and gets 404 without the two permissions.
