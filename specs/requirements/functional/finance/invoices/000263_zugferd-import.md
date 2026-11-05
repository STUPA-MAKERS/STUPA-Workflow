---
id: "000263"
title: A ZUGFeRD invoice fills the form
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
---

# A ZUGFeRD invoice fills the form

An uploaded ZUGFeRD or Factur-X PDF fills the invoice data from its embedded XML. The import
tolerates invoices that a strict EN16931 check refuses. The embedded XML is limited to 16 MiB.
