---
id: "000635"
title: A page with Speichern offers Verwerfen in its header
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/pages/admin
---

# A page with Speichern offers Verwerfen in its header

A page of Verwaltung that shows the floating "Speichern" (`NF/usability/layout/000198`) must
show "Verwerfen" as a text button on the title row while there are unsaved changes.
"Verwerfen" must set every field back to the saved value and must then hide together with
"Speichern". It is the one action of the header (`NF/usability/layout/000197`).

Reason: Only Hilfe & Tickets and Übersetzungen offer "Verwerfen". On the other settings pages
the user must load the page again to drop a change.

Test: A unit test of each settings page changes a field, expects "Verwerfen" and
"Speichern", activates "Verwerfen" and expects the saved value and neither button.
