---
id: "002722"
title: Each Postfach has a switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "backend/tests/integration/modules/tickets/test_ticket_mail_fetch.py:test_the_fetch_opens_no_connection_while_the_switch_is_off"
implementation:
  - backend/worker/ticket_mail.py
  - backend/app/modules/tickets/mailbox.py
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# Each Postfach has a switch

A Postfach must have a switch. While the switch is off, the platform must not connect to the
IMAP account and must not send a mail through the SMTP account. A public message on a mail
ticket must then answer 409 `mailbox_off`.

The connection test that an admin starts by hand on the admin page is the exception: it must
run also while the switch is off.

Reason: An admin must be able to stop the mail traffic at once, for example after a wrong
setting, without the loss of the settings (000759). The test must run before the switch goes on, so the
admin knows that the settings work before the platform fetches and sends mails.

Test: A unit test runs the fetch with the switch off and expects no connection.
