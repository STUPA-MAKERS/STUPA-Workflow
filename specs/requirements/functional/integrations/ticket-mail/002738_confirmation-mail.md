---
id: "002738"
title: A new mail ticket gets a confirmation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# A new mail ticket gets a confirmation

While the switch `Eingang bestätigen` of a Bereich is on, the sender of a mail that became a new
ticket must get a mail with the number of the ticket. The mail must carry `Auto-Submitted:
auto-replied` and the thread headers (002734). One address must get at most one confirmation an
hour.

Reason: The sender learns that the mail arrived and gets the number for a question. The limit
and the header stop a loop with an automatic sender.

Test: A unit test imports two new mails of one address in one hour and expects one confirmation.
