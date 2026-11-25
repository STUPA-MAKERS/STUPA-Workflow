---
id: "003086"
title: The pretix sales are booked automatically
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The pretix sales are booked automatically

An Event with a linked pretix event must have the field `Einnahmen-Kostenstelle`. Only a person
who writes the Event and holds `budget.book` must set it. When the Event reaches a status of the
phase `done` (003036) and has no Mollie payments (003095), the worker must make one booking of
the kind income on this cost centre with the sum of the paid orders minus the refunds, the date
of the status change, the Event as link and the name of the pretix event in the text. The
booking must name `Pretix` as its author in the audit entry. A later change of the sales must
not change the booking. Without the field, the platform must not book. A booking that the
platform cannot make, for example in a closed fiscal year (000252), must show on the admin page
`Pretix` with its cause, and the section `Verkauf` must show the difference between the paid
sales and the income bookings that link the Event.

Reason: The money of a shop must reach the budget without typing. The person who sets the cost
centre decides where the money goes, and a booking that does not change after the day of the
Event keeps the books stable.

Test: A backend unit test sets an Event with two paid orders and one refund to the phase `done`
and reads one income booking with the sum, and reads no booking for an Event without the field.
