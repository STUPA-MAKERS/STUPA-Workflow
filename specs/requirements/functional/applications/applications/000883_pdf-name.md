---
id: "000883"
title: The Antrag PDF is named after the Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/documents
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - backend/app/modules/pdf
  - typst
  - frontend/src/app/pages/applications
---

# The Antrag PDF is named after the Antrag

The file name of the Antrag PDF must be `Antrag_<Titel>_<YYYY-MM-DD>.pdf`, with the date of
receipt. The title must use the same cleanup as the protocol file name (000118).

Reason: A folder of downloads must show which file holds which Antrag.

Test: Unit test of the file name function.
