---
id: "002869"
title: The detail of an Antrag has the section Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
---

# The detail of an Antrag has the section Bestellungen

The detail of an Antrag of a type with money must have the section "Bestellungen" below the
details. Each row must show the Bezeichnung, the Händler, the status, the price and the marks of
002880. The price must be the real price, else the planned price with the word "geplant". When
the real price and the planned price differ, the row must show the difference in euro with its
sign. Below the rows a line must show the sum and the approved amount. The heading must not show
a count.

Reason: The work on a purchase starts at the Antrag. The planned price is what the Gremium saw,
so a deviation and the spent part of the approved amount must show at once.

Test: A frontend unit test renders an Antrag with two Bestellungen, one with 100,00 € planned
and 112,50 € real, and reads the rows, "+12,50 €", the sum line and the heading.
