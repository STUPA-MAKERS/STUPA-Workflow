---
id: "002890"
title: The global search finds Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/search
  - backend/app/modules/budget
---

# The global search finds Bestellungen

The global search must have the source "Bestellungen". It must search in the number, the
Bezeichnung, the Händler and the Bestellnummer. It must use the read rule of 002863
(F/collaboration/search/000328). A hit must open the Bestellung in the detail of its Antrag.

Reason: A person who holds an invoice knows the Händler or the Bestellnummer and not the Antrag.

Test: A backend integration test finds a Bestellung by its Bestellnummer and finds nothing as a
person without the read of the Antrag.
