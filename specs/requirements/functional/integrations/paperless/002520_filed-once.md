---
id: "002520"
title: A file is filed only once
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# A file is filed only once

The platform must store the number of the Paperless document for each file that it files. The
platform must not file a file that has a stored number or an open job.

Reason: A retry or a second event must not make a second document of the same file.

Test: A unit test runs the filing job two times for one file and expects one upload.
