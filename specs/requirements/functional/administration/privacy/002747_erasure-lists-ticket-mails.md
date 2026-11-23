---
id: "002747"
title: An erasure names the mails that stay on the mail server
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/privacy
  - backend/app/modules/tickets
---

# An erasure names the mails that stay on the mail server

The erasure of a person or of an address must anonymize the mail tickets of each address of that
person (002716). The admin who does the erasure must see, for each Postfach, the count of the
mails of these addresses that the platform imported or sent. The platform must not delete these
mails on the mail server (002731).

Reason: A copy on the mail server stays after the anonymization in the platform. A person must
decide on it there, because a mail can have a retention duty (002532).

Test: A unit test erases an address with two imported mails and expects the Postfach with the
count 2 in the list.
