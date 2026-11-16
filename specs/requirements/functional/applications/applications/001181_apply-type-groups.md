---
id: "001181"
title: Step 1 shows the Antragsarten by group with the group text
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

# Step 1 shows the Antragsarten by group with the group text

The step "Antragsart wählen" of the apply wizard must show each group that holds at least one
offered Antragsart as one block. The block must show the name of the group as a heading, then
the text of the group, then the Antragsarten of the group. The text must always be visible. A
group without an offered Antragsart must not be shown. The text and the name must be in the UI
language, with German as the fallback.

Reason: The text helps the applicant choose, so it must be readable before the choice.

Test: The wizard tests check the heading, the text and the types of each group, and that an
empty group is not shown.
