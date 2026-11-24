---
id: "002869"
title: The Antrag detail has the section Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
---

# The Antrag detail has the section Bestellungen

The detail of an Antrag of a type with money must have the section "Bestellungen" below the
details. Each row must show the Bezeichnung, the Händler, the status, the price and the marks of
002879. The price must be the real price, else the planned price with the word "geplant". Below
the rows a line must show the sum and the approved amount. The heading must not show a count.

Reason: The work on a purchase starts at the Antrag. The line with the sum shows at once how
much of the approved amount is spent.

Test: A frontend unit test renders an Antrag with two Bestellungen and reads the rows, the sum
line and the heading.
