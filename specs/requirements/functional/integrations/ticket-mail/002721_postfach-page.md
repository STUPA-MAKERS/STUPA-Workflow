---
id: "002721"
title: An admin sets the Postfach on the admin page
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
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
