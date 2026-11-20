---
id: "001720"
title: A denied or returned Antrag offers a new version
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/applications/service/new_version.py
  - backend/app/modules/applications/links_router.py
  - frontend/src/app/features/apply/status-timeline.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A denied or returned Antrag offers a new version

An Antrag in a state with the flag `Abgelehnt` or in a state with `editAllowed` that is not
the initial state must offer the button `Neue Fassung` (`New version`) to its applicant and to a
person with the permission `application.manage`. The button must create a new draft of the same
Antragsart. The draft must get the values and the Kostenaufstellung of the Antrag as 000544
prefills them. Files must not be copied.

Reason: Prod data holds 4 second versions of an Antrag. The applicants typed everything again.

Test: A backend integration test creates a new version and checks the prefilled values.
