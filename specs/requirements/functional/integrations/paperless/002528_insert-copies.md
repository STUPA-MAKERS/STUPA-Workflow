---
id: "002528"
title: An insert from Paperless copies the document as an embedded PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---

# An insert from Paperless copies the document as an embedded PDF

A pick in the Paperless search (002534) must copy the PDF version of the document from Paperless into the
platform. The copy must pass each check of a PDF upload (NF/security/files/000869). The editor
must insert it as an embedded PDF (000862) with the title of the document as its name. The
platform must store the number of the Paperless document with the copy.

Reason: A copy is a file of the platform. It follows the read right of its Sitzung and stays
when the document changes in Paperless. The platform then shows no preview from Paperless.

Test: A unit test inserts a document and expects a stored PDF with the document number.
