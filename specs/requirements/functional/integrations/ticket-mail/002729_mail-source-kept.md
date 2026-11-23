---
id: "002729"
title: The platform keeps the source of each mail
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/app/modules/files
---

# The platform keeps the source of each mail

The platform must store the full source of each imported and each sent mail as a file of its
message. A person with the work right must be able to download it. The anonymization of the
ticket must delete it.

Reason: The text conversion loses the form and the headers of a mail. The source is the proof of
what arrived and of what the team sent.

Test: A unit test imports a mail, anonymizes the ticket and expects no stored source.
