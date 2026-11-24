---
id: "002816"
title: A mail message of an unchecked sender is marked
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/tickets/mail_import.py
  - backend/app/modules/tickets/models.py
  - frontend/src/app/pages/tickets
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A mail message of an unchecked sender is marked

A message that a mail adds to a ticket must count as checked only when its `In-Reply-To` or
`References` names a mail that the Postfach sent to the address in `From`. Each other message of
a mail must show the hint `Absender nicht geprüft` in the ticket. A ticket that a mail makes must
show the same hint on its first message.

Reason: The `From` of a mail is not checked (002739). A person who knows the address of the sender
and the number of a ticket can write in the name of that sender (002727). Only a recipient of a
mail of the Postfach knows its message id. A header `Authentication-Results` does not count,
because the sender can write one too.

Test: A unit test imports a mail with the number and the address of the sender and no thread
header, and expects the hint. A unit test imports an answer to a sent mail and expects no hint.
