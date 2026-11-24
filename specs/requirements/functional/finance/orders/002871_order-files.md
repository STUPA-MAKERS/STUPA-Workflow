---
id: "002871"
title: A file of a Bestellung is an attachment of its Antrag
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/files
  - backend/app/modules/budget
  - frontend/src/app/pages/applications
---

# A file of a Bestellung is an attachment of its Antrag

The form of a Bestellung must take files, for example the confirmation of the order. The server
must store each file as an attachment of the Antrag with a reference to the Bestellung, like a
file of a position (F/applications/forms/001730). The Antrag detail must show the file at the
Bestellung and in the attachments list. An applicant session must not read a file of a
Bestellung.

Reason: The attachments of an Antrag already have the scan, the storage and the download. A
second file store would copy them. The confirmation of an order can hold the data of the shop
account.

Test: A backend integration test uploads a file to a Bestellung, reads it with its reference and
gets 404 with an applicant session.
