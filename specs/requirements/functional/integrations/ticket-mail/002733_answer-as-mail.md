---
id: "002733"
title: A public message on a mail ticket goes out as a mail
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A public message on a mail ticket goes out as a mail

A public message of the team on a ticket whose sender is an e-mail address must go out as a mail
through the SMTP account of the Postfach of the Bereich, with the full text and the files of the
message. An internal message must never go out.

Reason: The sender of a mail has no account and no view in the app, so the mail is the answer.

Test: A unit test writes one public and one internal message and expects one mail with the text
of the public one.
