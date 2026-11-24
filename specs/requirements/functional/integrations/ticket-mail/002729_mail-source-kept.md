---
id: "002729"
title: The platform keeps the source of each mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_the_source_is_kept_and_the_anonymization_deletes_it"
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_a_source_without_a_clean_scan_stays_closed"
  - "frontend/src/app/pages/tickets/ticket-detail.component.spec.ts:TicketDetailComponent"
implementation:
  - backend/app/modules/tickets/mail_import.py
  - backend/app/modules/tickets/service/mail.py
  - backend/app/modules/tickets/router.py
  - frontend/src/app/pages/tickets/ticket-detail.component.ts
  - mcp/antragsplattform_mcp/tools/tickets.py
scope:
  - backend/app/modules/tickets
  - backend/app/modules/files
---

# The platform keeps the source of each mail

The platform must store the full source of each imported and each sent mail as a file of its
message. A person with the work right must be able to download it. The anonymization of the
ticket must delete it.

Reason: The text conversion loses the form and the headers of a mail. The source is the proof of
what arrived and of what the team sent.

Test: A unit test imports a mail, anonymizes the ticket and expects no stored source.
