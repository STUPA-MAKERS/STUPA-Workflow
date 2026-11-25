---
id: "001730"
title: A position takes files in the form
kind: functional
status: removed
owner: frederikbeimgraben
updated: 2026-11-24
scope:
  - backend/app/modules/files
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# A position takes files in the form

Each position of a `positions` field must have an upload for files in the form. A file must
be stored as an attachment of the Antrag with a reference to its position. The Antrag detail
must show the files of a position below the position and in the attachments list.

Reason: Prod data holds 30 of 62 submitted Anträge with money and without a file. The applicant did not see where the offers go.

Test: A backend integration test uploads a file to a position and reads it with its position.
