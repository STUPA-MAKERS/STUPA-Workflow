---
id: "002716"
title: Closed tickets are anonymized after the retention time of the Bereich
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# Closed tickets are anonymized after the retention time of the Bereich

Each Bereich must hold its retention time in months, or none. A cron must anonymize a ticket
whose `closed_at` is older than the retention time of its Bereich. The sender, the addresses of
the mails, the context, the attachments and the stored mails must go. Title, text, messages and
events must stay.

Reason: The teams have different duties to keep data: a question on the platform is short lived,
a case of the finances is not.

Test: A unit test closes one ticket in each of two Bereiche with different times and expects
only one anonymized.
