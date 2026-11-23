---
id: "002730"
title: The attachments of a mail become files of the message
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - backend/app/modules/files
---

# The attachments of a mail become files of the message

Each attachment and each inline image of an imported mail must become a file of its message,
with the virus scan and the quarantine of each upload (000340). A file above the size limit
(000339) must be left out, and the message must name each left-out file with its size.

Reason: A file from a stranger needs the same checks as an upload. The limit holds for each file
on the platform, and the stored source still has the large file (002729).

Test: A unit test imports a mail with one small and one too large file and expects one file and
one named file.
