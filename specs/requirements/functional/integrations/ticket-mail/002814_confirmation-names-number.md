---
id: "002814"
title: The confirmation names only the number of the ticket
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/tickets/mail_send.py
scope:
  - backend/app/modules/tickets
---

# The confirmation names only the number of the ticket

The subject and the text of a confirmation (002738) must name the number of the ticket and must
not hold the subject, the text or another value of the incoming mail.

Reason: The `From` of a mail is not checked (002739). A confirmation with the subject of the mail
lets a stranger send a text of their own from the address of the Bereich to any address.

Test: A unit test imports a mail with a subject and expects a confirmation whose subject and text
do not hold that subject.
