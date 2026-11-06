---
id: "000260"
title: An invoice is a document with many bookings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget
scope:
  - backend/app/modules/budget
---

# An invoice is a document with many bookings

One invoice can have many bookings. The delete of an invoice must keep its bookings and must
remove the link.
