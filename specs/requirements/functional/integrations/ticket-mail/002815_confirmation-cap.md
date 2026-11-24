---
id: "002815"
title: A Postfach sends at most 30 confirmations an hour
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/tickets/mail_send.py
scope:
  - backend/app/modules/tickets
---

# A Postfach sends at most 30 confirmations an hour

A Postfach must send at most 30 confirmations (002738) in one hour, over all addresses. A new
ticket above the limit must get no confirmation, and the ticket itself must still be made.

Reason: The limit of one address an hour does not stop a sender who uses a new forged address for
each mail. The cap keeps the address of the Bereich out of the block lists of the mail providers.

Test: A unit test imports 31 new mails of 31 addresses in one hour and expects 30 confirmations.
