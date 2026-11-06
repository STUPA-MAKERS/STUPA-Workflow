---
id: "000130"
title: PII fields need application.read
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/applications/access.py
  - backend/app/modules/applications/service/listing.py
  - backend/app/modules/applications/service/reads.py
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# PII fields need application.read

A field marked as PII must show only to `application.read`, `application.read_all`, an admin,
the applicant and the logged-in creator. The list search must skip PII values for a caller
without that right, except in the own Anträge.

Reason: Else the search tells which Antrag holds a guessed name or IBAN.
