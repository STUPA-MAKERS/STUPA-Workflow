---
id: "001184"
title: Step 1 has no general text, only the group texts
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/features/apply/apply-wizard.component.spec.ts:ApplyWizardComponent"
implementation:
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/branding
  - backend/app/modules/site_config
scope:
  - backend/app/modules/application_types
  - backend/app/modules/admin
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# Step 1 has no general text, only the group texts

The step "Antragsart wählen" must show no general text under the Antragsarten. The branding must
not have the free text "Info unter der Antrags-Auswahl" (`applyInfo`) any more. A saved value of
it must be ignored and must not be shown. Only the texts of the groups explain the Antragsarten.

Reason: One long text under the list mixed the explanations of all types. Each part now belongs
in the text of its group.

Test: The wizard tests check that the step shows no general text. The branding tests check that
the editor has no field `applyInfo`.
