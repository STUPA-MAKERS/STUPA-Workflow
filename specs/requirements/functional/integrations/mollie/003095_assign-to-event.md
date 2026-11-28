---
id: "003095"
title: A Mollie payment belongs to the Event of its pretix shop
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/event_sales/mollie_sync.py
scope:
  - backend/app/
  - frontend/src/app/
---
# A Mollie payment belongs to the Event of its pretix shop

The platform must assign a Mollie payment to an Event when the metadata of the payment names the
organizer and the pretix event that the Event links (003083). A payment without such metadata
must not belong to an Event and is booked by 003103. The platform must not assign a payment by its amount, its date or
its text.

Reason: The pretix payment provider for Mollie writes the organizer and the event into each
payment. A rule from the metadata alone is exact, and a guess by amount or text can put money on
the wrong Event.

Test: A backend unit test reads two fake payments, one with the metadata of a linked pretix event
and one without, and finds only the first at the Event.
