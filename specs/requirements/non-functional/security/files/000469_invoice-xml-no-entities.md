---
id: "000469"
title: The ZUGFeRD XML parser resolves no entities
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/invoice_import.py
scope:
  - backend/app/modules/budget/invoice_import.py
---

# The ZUGFeRD XML parser resolves no entities

The invoice import must parse the embedded XML without a DTD, without entities and without
network access.

Reason: A DTD allows XXE, SSRF and a billion-laughs attack.
