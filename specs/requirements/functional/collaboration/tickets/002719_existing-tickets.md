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
menu, and must keep its number of the form `T-0042`, its kind as the Kategorie, its status, its
messages and its events. The settings `notifyNew` and `retentionMonths` must become the settings
of `Plattform`.

Reason: The holders of `ticket.manage` must find each ticket and each rule after the update as
before. The old numbers stand in mails and in to-do cards, so they must stay valid beside the
random numbers of the new tickets (002714).

Test: An integration test migrates a database with a ticket and expects the ticket in
`Plattform` with the same number.
