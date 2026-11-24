---
id: "002854"
title: A status change fills an empty date
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
---

# A status change fills an empty date

A change to the status "Bestellt" must set `orderedOn` to the current day when the field is
empty. A change to the status "Geliefert" must set `deliveredOn` to the current day when the
field is empty. A status change must not change a date that a person set.

Reason: The person who reports a delivery does it with one click. A date that the person typed
is more exact than the day of the click.

Test: A backend unit test sets "Geliefert" on a Bestellung without dates and on one with a typed
date, and reads both dates.
