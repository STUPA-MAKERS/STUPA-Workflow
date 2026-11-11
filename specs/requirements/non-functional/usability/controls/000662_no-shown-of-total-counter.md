---
id: "000662"
title: A list shows no "X von Y" counter
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/pages/invoices
  - frontend/src/app/features/voting
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A list shows no "X von Y" counter

A list page must not show a counter of the form "X von Y" beside the filters or below the
list. This applies to "4 von 4" beside the filter chips of Rechnungen and to "2 von 2
Abstimmungen" below the list of Abstimmungen.

Reason: The search field names the count (000661). A second count beside it changes while the
person filters and adds no information.

Test: A unit test of the two pages expects no element with a text of this form.
