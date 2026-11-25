---
id: "003084"
title: The detail of an Event shows the pretix sales
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The detail of an Event shows the pretix sales

The detail of an Event with a linked pretix event must have the section `Verkauf`. It must show
for each product the number of paid, pending and cancelled positions, the sum of the paid
orders, the sum of the refunds and the free places of each quota, and the time of the last read
(003085). Each person who reads the Event must see the section. The section must show only
these sums and numbers (003088).

Reason: The people who plan an Event need the number of guests and the money in one place, and
they must not need an account in pretix for it.

Test: A frontend unit test opens an Event with sales and reads the products, the sums and the
time of the last read.
