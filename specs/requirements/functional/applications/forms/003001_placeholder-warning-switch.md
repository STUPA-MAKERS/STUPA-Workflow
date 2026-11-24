---
id: "003001"
title: The placeholder warning is a setting of the positions field
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

# The placeholder warning is a setting of the positions field

A `positions` field must have the setting `validation.placeholderWarning`. The default is on.
When it is off, the form must not show the warnings of 001640 at the offers of this field and
must not show the line that names the switch for no comparison offers. The form editor must show
the switch `Platzhalter-Angebote markieren` (`Flag placeholder offers`) at a `positions` field.

Reason: A form for small purchases can have offers of 1 € or short supplier names on purpose.
The finance officer decides per form whether the form warns.

Test: A frontend unit test renders an offer of 1 € with the setting off and finds no warning.
