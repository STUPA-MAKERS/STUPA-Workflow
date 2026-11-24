---
id: "002876"
title: Rechnung anlegen opens the invoice form from the Bestellung
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/invoices
---

# Rechnung anlegen opens the invoice form from the Bestellung

The entry "Rechnung anlegen" of a Bestellung must open the invoice form with the Händler as the
supplier. The form must keep the import of a ZUGFeRD file. When the person saves, the new
invoice must become the invoice of the Bestellung.

Reason: The invoice often arrives after the delivery, and the person has the Bestellung open
then. A second way through the invoice list loses the relation.

Test: A frontend unit test picks the entry, saves the form and expects the request that sets the
invoice of the Bestellung.
