---
id: "002863"
title: A person who reads the Antrag reads its Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
  - backend/app/modules/applications
---

# A person who reads the Antrag reads its Bestellungen

A person must read a Bestellung when the person reads its Antrag. The server must answer 404 for
a Bestellung of an Antrag that the person does not read.

Reason: The Bestellungen are a part of the story of an Antrag. A second read rule would hide
them from the Gremium that decided the Antrag.

Test: A backend integration test reads the Bestellungen as a member of the Gremium of the Antrag
and gets 404 as a person without the read of the Antrag.
