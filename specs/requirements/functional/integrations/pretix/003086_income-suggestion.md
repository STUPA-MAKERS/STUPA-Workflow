---
id: "003086"
title: The paid sales become a suggested income booking
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The paid sales become a suggested income booking

The section `Verkauf` of an Event must have the action `Einnahme buchen`. It must open the form
of a new booking of the kind income with the sum of the paid orders minus the refunds, the
Event as link and the name of the pretix event in the text. A person must choose the cost centre
and save the booking, and the save must need the permission of each booking. The platform must
not book money without the save of a person. The section must show the difference between the
paid sales and the income bookings that link the Event.

Reason: A booking moves the budget of a cost centre, and the student government is responsible
for each booking. The suggestion saves the typing, and the difference shows money that is not
booked yet.

Test: A backend unit test reads the suggestion of an Event with two paid orders and one refund,
and finds no booking before a save.
