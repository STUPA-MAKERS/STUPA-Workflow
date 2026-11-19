---
id: "001710"
title: A draft says that it is not submitted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A draft says that it is not submitted

An Antrag in the initial state of the flow is a draft. The detail of a draft must show the
note `Noch nicht eingereicht` (`Not submitted yet`) with the button `Einreichen` (`Submit`) at
the top. The button fires the manual transition of the applicant out of the initial state. The
list row of a draft must show `Noch nicht eingereicht` (`Not submitted yet`).

Reason: Prod data holds 4 drafts that the Finanzreferat submitted and 5 drafts older than 14 days. The applicants thought that the draft was submitted.

Test: A frontend unit test renders the detail and the list row of a draft.
