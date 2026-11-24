---
id: "002721"
title: An admin sets the Postfach on the admin page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/unit/modules/tickets/test_ticket_router.py:test_the_postfach_routes_need_admin_ticket_mail"
  - "backend/tests/unit/modules/tickets/test_ticket_mailbox.py:test_the_test_logs_in_to_both_accounts"
  - "frontend/src/app/pages/admin/help-tickets/ticket-mailbox-dialog.component.spec.ts:TicketMailboxDialogComponent"
implementation:
  - backend/app/modules/tickets/router.py
  - backend/app/modules/tickets/mailbox.py
  - backend/app/shared/permissions.py
  - frontend/src/app/pages/admin/help-tickets/ticket-mailbox-dialog.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# An admin sets the Postfach on the admin page

The settings of a Bereich on the admin page `Hilfe & Tickets` must hold the Postfach: address,
IMAP host, port, user and password, SMTP host, port, user and password, and the folder for the
done mails. A button must test both connections and show the result of each. The settings of a
Postfach must need the permission `admin.ticket_mail`.

Reason: The Postfach holds the password of a mail account and lets the server connect to a host,
so only an admin must set it (002744).

Test: A unit test saves a Postfach without the permission and expects 403.
