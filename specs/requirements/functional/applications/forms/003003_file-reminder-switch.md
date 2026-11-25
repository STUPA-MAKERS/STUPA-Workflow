---
id: "003003"
title: The question about a missing file is a setting of the positions field
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-24
replaced_by: F/applications/forms/003010
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# The question about a missing file is a setting of the positions field

A `positions` field must have the setting `validation.fileReminder`. The default is on. The
warning of 001731 must show only when the form has a `positions` field with this setting on. The
form editor must show the switch `Ohne Anhang nachfragen` (`Ask when no file is attached`) at a
`positions` field. The switch `Anhang Pflicht` of 001732 stays as it is.

Reason: A form without offers, for example a reimbursement of a fixed fee, has positions but no
file to attach. The question then only slows down the applicant.

Test: A frontend unit test submits without a file with the setting off and finds no warning.
