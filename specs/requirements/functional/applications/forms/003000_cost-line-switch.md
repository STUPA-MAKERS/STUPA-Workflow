---
id: "003000"
title: The cost line is a setting of the positions field
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-24
replaced_by: F/applications/forms/003010
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
  - frontend/src/app/pages/admin/forms
---

# The cost line is a setting of the positions field

A `positions` field must have the setting `validation.costLine`. The default is on. When it is
off, the form must not show the line of 001630 and 001631 below the positions of this field. The
sum row of 003008 must stay. The form editor must show the switch
`Summenzeile anzeigen` (`Show summary line`) at a `positions` field. The setting must not change
a computation or a check.

Reason: A form that shows the funding rate and the funding per participant as own fields repeats
the values of the line. The finance officer decides per form which texts the form shows.

Test: A frontend unit test renders a `positions` field with `costLine: false` and finds no line
"Gesamtkosten". A backend unit test saves the setting and reads it back.
