---
id: "002417"
title: The payload is built when the event occurs
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
protocols:
  - "P/integrations/webhooks/000963"
implementation: null
scope:
  - backend/app/modules/webhooks
---

# The payload is built when the event occurs

The platform must build the body of a delivery in the same transaction as the event and must store
it with the delivery. A retry must send the stored body. A rolled back transaction must create no
delivery. A change of the webhook config must not change a delivery that already exists.

Reason: A retry hours later must not send different data than the event had. A delivery for a
change that never happened would be wrong.

Test: A unit test changes an Antrag after the dispatch and checks that the retry sends the old
values.
