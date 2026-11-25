---
id: "003086"
title: Each paid pretix order is booked automatically
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# Each paid pretix order is booked automatically

An Event with a linked pretix event must have the field `Einnahmen-Kostenstelle`. Only a person
who writes the Event and holds `budget.book` must set it. While the switch `Einnahmen buchen`
(003082) is on and the field is set, the worker must make one booking of the kind income for
each paid order of the pretix event: with the sum of the order, the date of the payment, the
code of the order in the text, and a link to the Event (003033). A refund or a cancellation of a
paid order must become one more booking that takes the refunded sum off the income, with the
same link. Each order and each refund must be booked only once. When an admin sets the field
later, the worker must also book the paid orders before that day. The booking must name `Pretix`
as its author in the audit entry. Without the field, the platform must not book. A booking that
the platform cannot make, for example in a closed fiscal year (000252), must show on the admin
page `Pretix` with its cause.

Reason: One booking per order links each income to the Event, so the totals of the Event
(000479) hold every sale, also cash. The code of the order finds the sale in pretix again.

Test: A backend unit test reads two paid orders and one refund of a linked pretix event and
finds three bookings linked to the Event, and runs the cron again and finds no new booking.
