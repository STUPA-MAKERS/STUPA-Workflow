---
id: "000880"
title: An Antrag downloads as PDF
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/applications/pdf.py
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - backend/app/modules/pdf
  - typst
  - frontend/src/app/pages/applications
---

# An Antrag downloads as PDF

The three-dot menu of the Antrag detail page must have the action "Als PDF herunterladen". The
action must download `GET /api/applications/{id}/pdf`. Each person who can read the Antrag
must be able to download it: a reader with `application.read`, an applicant, an observer and
the creator. The PDF must show the current version of the Antrag. The download must stream
through the API and never use a presigned URL (000178).

Reason: An Antrag goes to people outside the platform, for example to the Finanzreferat or
to an archive. They need one file that holds the full Antrag.

Test: Integration test of the route: a reader gets `application/pdf`, a person without read
access gets 404.
