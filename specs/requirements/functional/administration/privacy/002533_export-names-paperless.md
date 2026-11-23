---
id: "002533"
title: The data export names the filed Paperless documents
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
---

# The data export names the filed Paperless documents

The data export of a person (000458) must name each Paperless document that the platform filed
for an Antrag of that person, with its number and the date of the filing.

Reason: The person has the right to learn where copies of the personal data are.

Test: A unit test exports the data of a person with a filed Antrag and expects the document
number in the workbook.
