---
id: "002937"
title: The form of a Bestellung opens in the pane of the page
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages
---

# The form of a Bestellung opens in the pane of the page

The create and the change of a Bestellung must use a form in the detail pane of the page
"Bestellungen", like the form of a booking, and must not use a dialog. The button "Bestellung
anlegen" of the page must open the empty form, in which the person picks an approved Antrag of a
type with money that the person reads. The action "Bestellung anlegen" of an Antrag (002869) and
of a row of the segment "Ohne Bestellung" (002934) must open the form with that Antrag set. The
address `/orders?new=order&application=<id>` must open the form with this Antrag.

Reason: The form has many fields, and a pane gives them room and keeps the list in view. One
form for every way in keeps the rules of 002861 in one place.

Test: A frontend unit test opens `/orders?new=order&application=<id>`, reads the Antrag in the
form, saves and expects the create request for this Antrag.
