---
id: "002716"
title: The anonymization of a ticket removes its mail data
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# The anonymization of a ticket removes its mail data

One retention time, the setting `tickets.retentionMonths`, must hold for the tickets of each
Bereich (000316). The anonymization of a ticket must also remove the name and the address of
the sender of a mail, each `Cc` address, the mail headers and the stored mails (002729).

Reason: One time for the whole platform is one rule that each team knows. The addresses and the
stored mails are personal data of the sender like the reporter of a report.

Test: A unit test anonymizes a mail ticket and expects no address, no header and no stored
mail.
