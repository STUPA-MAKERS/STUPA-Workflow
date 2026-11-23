---
id: "002719"
title: The tickets from before the Bereiche belong to Plattform
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The tickets from before the Bereiche belong to Plattform

The migration must put each existing ticket into the Bereich `Plattform` with the source help
menu, and must keep its kind as the Kategorie, its status, its messages and its events. The
migration must give each existing ticket a new random number (002714). A number of the old form
`T-0042` must find no ticket. The setting `notifyNew` must become the setting of `Plattform`.

Reason: The holders of `ticket.manage` must find each ticket and each rule after the update as
before. One form of the number for all tickets leaves no number that a person can guess.

Test: An integration test migrates a database with the ticket `T-0042` and expects the ticket in
`Plattform` with a number of the new form and no ticket for `T-0042`.
