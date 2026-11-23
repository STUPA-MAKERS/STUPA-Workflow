---
id: "002724"
title: A mail is imported one time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/worker
---

# A mail is imported one time

The platform must import a mail of a Postfach only once. The `Message-ID` together with the
Postfach is the identity of a mail. A mail without a `Message-ID` must get the SHA-256 of its
source as identity.

Reason: A second run after a failure, and a mail that a person moves back to the inbox, must not
make a second ticket.

Test: A unit test fetches the same mail two times and expects one ticket.
