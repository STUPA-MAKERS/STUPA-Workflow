---
id: "000263"
title: A ZUGFeRD invoice fills the form
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/budget
---

# A ZUGFeRD invoice fills the form

An uploaded ZUGFeRD or Factur-X PDF must fill the invoice data from its embedded XML. The
import must tolerate invoices that a strict EN16931 check refuses. The embedded XML must be at
most 16 MiB.
