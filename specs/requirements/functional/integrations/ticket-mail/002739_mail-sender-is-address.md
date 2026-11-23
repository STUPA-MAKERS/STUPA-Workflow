---
id: "002739"
title: The sender of a mail ticket is the address, not an account
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The sender of a mail ticket is the address, not an account

A ticket from a mail must have the `From` address as its sender, also when an account has the
same address. Such a ticket must not show in the tab `Tickets` of that account.

Reason: The `From` of a mail is not checked. A link to the account would put the text of a
stranger into the view of a person.

Test: A unit test imports a mail with the address of an account and expects an empty list of own
tickets for that account.
