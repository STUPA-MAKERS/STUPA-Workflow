---
id: "002934"
title: The list shows the approved Anträge without a Bestellung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# The list shows the approved Anträge without a Bestellung

The segment "Ohne Bestellung" of the page "Bestellungen" must list each Antrag that the person
reads, that is in a state with the flag approved, that is of a type with money and that has no
Bestellung that is not "Storniert". Each row must show the title, the Gremium and the approved
amount of the Antrag and must open the Antrag. For a person with `order.manage` the row must
have the action "Bestellung anlegen". The server must read only the flag of the state and must
not compare the key of a state.

Reason: Only a person creates a Bestellung (002930), so nothing tells that a purchase is due.
This segment is the list of the work that waits, in each installation and with each flow.

Test: A backend integration test lists an approved Antrag without a Bestellung, does not list it
after the create of a Bestellung and lists it again after the cancel of this Bestellung.
