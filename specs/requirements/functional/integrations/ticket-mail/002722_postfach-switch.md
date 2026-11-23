---
id: "002722"
title: Each Postfach has a switch
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# Each Postfach has a switch

A Postfach must have a switch. While the switch is off, the platform must not connect to the
IMAP account and must not send a mail through the SMTP account. A public message on a mail
ticket must then answer 409 `mailbox_off`.

Reason: An admin must be able to stop the mail traffic at once, for example after a wrong
setting, without the loss of the settings (000759).

Test: A unit test runs the fetch with the switch off and expects no connection.
