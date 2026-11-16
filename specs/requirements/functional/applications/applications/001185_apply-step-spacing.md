---
id: "001185"
title: The blocks of step 1 have one even spacing
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

# The blocks of step 1 have one even spacing

The blocks of the step "Antragsart wählen" (the groups, the types without a group and the field
"Folgeantrag") must have the same vertical gap between them. The heading "Folgeantrag" must have
the style of the group headings.

Reason: Before this rule the field "Folgeantrag" had a larger gap above it than the gap below it,
so the field and the text under it looked like one block.

Test: The wizard tests check that the step has no extra margin on the field "Folgeantrag".
