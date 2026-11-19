---
id: "001732"
title: An Antragsart can require a file
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/files
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# An Antragsart can require a file

An Antragsart must have the switch `Anhang Pflicht` (`File required`). When it is on, the form
must block the submit while the Antrag has no attachment. The backend must refuse the submit, the
create of a submitted Antrag and the transition out of the initial state with 422
`attachment_required`.

Reason: An Antragsart such as Rückerstattung is useless without a receipt.

Test: A backend integration test submits an Antrag of such an Antragsart without and with a file.
