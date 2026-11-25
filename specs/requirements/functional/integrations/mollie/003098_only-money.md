---
id: "003098"
title: The platform keeps only the money data of Mollie
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The platform keeps only the money data of Mollie

The platform must store of a Mollie payment only its id, amount, fee, status, dates, settlement
and the metadata of 003095. It must not store, log or show the name, the email address, the IBAN,
the card data or a different personal value of the payer.

Reason: The bookings need only the money. Data that the platform does not hold needs no erasure
and no export.

Test: A backend unit test reads a fake payment with a consumer name and an IBAN and finds neither
value in the stored payment.
