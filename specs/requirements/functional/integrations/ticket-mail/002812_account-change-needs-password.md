---
id: "002812"
title: A change of a mail account needs its password again
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/tickets/mailbox.py
  - frontend/src/app/pages/admin/help-tickets/ticket-mailbox-dialog.component.ts
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/admin/help-tickets
---

# A change of a mail account needs its password again

A change of the host, the port or the user of the IMAP account must carry the IMAP password in the
same request. The same must apply to the SMTP account and its password. Without the password the
change must answer 422 with the code `password_required` and must change nothing.

Reason: A stored password must not follow a new host. Else a person with the admin page and
without the password can send it to another host of the allowlist with the button `Testen`.

Test: A unit test changes the IMAP host without a password and expects 422 `password_required`
and the old host.
