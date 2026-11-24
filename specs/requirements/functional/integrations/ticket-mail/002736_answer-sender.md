---
id: "002736"
title: A sent mail comes from the address of the Postfach
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_send.py:test_a_sent_mail_comes_from_the_postfach_with_the_signature"
  - "frontend/src/app/pages/admin/help-tickets/ticket-mailbox-dialog.component.spec.ts:TicketMailboxDialogComponent"
implementation:
  - backend/app/modules/tickets/mail_send.py
  - backend/app/modules/tickets/mailbox_schemas.py
  - frontend/src/app/pages/admin/help-tickets/ticket-mailbox-dialog.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A sent mail comes from the address of the Postfach

A sent mail of a ticket must have the address of the Postfach as `From` and the name of the
Bereich as its display name. The text must end with the signature of the Bereich, which an admin
sets. The mail must name the writer only when the signature has the placeholder `{name}`.

Reason: An answer from the address of the Postfach comes back to the Postfach, and the mail
server signs for its own address. The team decides if its members show by name.

Test: A unit test sends an answer and expects the address of the Postfach in `From`.
