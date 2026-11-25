---
id: "003094"
title: The worker reads the Mollie payments
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
  - backend/worker
---
# The worker reads the Mollie payments

A worker cron must read the new payments, refunds, chargebacks and settlements of the Mollie
account every hour. The platform must not receive webhooks from Mollie. A failed read must keep
the stored payments and show the time of the last read that worked on the admin page.

Reason: The data in Mollie changes slowly, and the settlement comes days after the payment. A
read by the worker needs no public route.

Test: A backend unit test runs the cron with a fake Mollie and reads the new payments, and runs
it a second time and reads no duplicate.
