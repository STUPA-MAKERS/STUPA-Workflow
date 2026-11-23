---
id: "002731"
title: An imported mail moves to a folder and is never deleted
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# An imported mail moves to a folder and is never deleted

After the import the platform must move a mail from the inbox to the folder for done mails of
the Postfach. The platform must create the folder when it is missing. The platform must not
delete a mail on the mail server.

Reason: The inbox then holds only what the platform did not import, so a person sees a problem
with a look into the mail account. The mail server stays the full record.

Test: A unit test of the mail client expects a move command and no delete command.
