---
id: "001173"
title: An old apply link with the type id still works
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/features/apply/apply-wizard.component.spec.ts:ApplyWizardComponent"
implementation:
  - frontend/src/app/features/apply/apply-wizard.component.ts
  - frontend/src/app/pages/dashboard/dashboard.component.html
scope:
  - frontend/src/app/features/apply
  - frontend/src/app/pages/dashboard
---

# An old apply link with the type id still works

A link to `/apply?type=<id>` must open the wizard as `/apply/<key>` of the type with that id,
and the browser history must not keep the old URL. The links of the platform to one Antragsart,
for example on the Start page, must use `/apply/<key>`.

Reason: Links with the type id are already in use, and they must not break.

Test: The wizard test opens `/apply?type=<id>` and checks the URL.
