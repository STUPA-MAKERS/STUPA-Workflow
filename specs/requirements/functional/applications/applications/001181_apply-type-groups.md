---
id: "001181"
title: Step 1 shows the Antragsarten by group with the group text
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/features/apply/apply-wizard.component.spec.ts:ApplyWizardComponent"
implementation:
  - frontend/src/app/features/apply
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# Step 1 shows the Antragsarten by group with the group text

The step "Antragsart wählen" of the apply wizard must give the groups of the offered
Antragsarten to the choice step of the kit (ui-kit:002282). The text and the name of a group must
be in the UI language, with German as the fallback.

Reason: The applicant reads the group text in the own language.

Test: The wizard tests check that each group holds only offered Antragsarten.
