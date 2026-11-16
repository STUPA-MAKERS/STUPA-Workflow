---
id: "001182"
title: Antragsarten without a group stand last under Weitere Anträge
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
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

# Antragsarten without a group stand last under Weitere Anträge

The step "Antragsart wählen" must show the Antragsarten without a group after the last group, as
one block with the heading "Weitere Anträge" (English "Other applications"). When the step shows
no group, it must show all Antragsarten as one list without a heading, as before.

Reason: Next to named groups, a block without a heading looks like a part of the group above it.
Without groups the step looks as it did before.

Test: The wizard tests check the heading and the position of the types without a group, and the
list without groups.
