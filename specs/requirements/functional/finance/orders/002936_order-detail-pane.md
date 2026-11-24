---
id: "002936"
title: The detail of a Bestellung shows all of it in one pane
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
---

# The detail of a Bestellung shows all of it in one pane

The detail of a Bestellung on the page "Bestellungen" must show, in this order: the Bezeichnung
with the number, the status and the marks of 002880; the actions of 002870; the fields of 002851
with the planned price, the real price and their difference in euro with its sign; the positions
of the Antrag that the Bestellung covers; the sum line of 002868; the files (002871); the list
"Verknüpft" (002889); the comments of the Antrag (002935). The detail must not be a dialog.

Reason: A person who works on a purchase needs its price, its papers and its relations at one
look. A dialog covers the list and shows only a part.

Test: A frontend unit test opens the detail of a Bestellung with 100,00 € planned and 112,50 €
real and reads the fields, "+12,50 €", the sum line and the sections in their order.
