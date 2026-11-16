---
id: "001171"
title: An apply link to an unknown Antragsart opens the type step
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/features/apply/apply-wizard.component.spec.ts:ApplyWizardComponent"
implementation:
  - frontend/src/app/features/apply/apply-wizard.component.ts
scope:
  - frontend/src/app/features/apply
---

# An apply link to an unknown Antragsart opens the type step

When the key in `/apply/<key>` names no Antragstyp that accepts an Antrag, the wizard must
replace the URL with `/apply` and show the type step. A toast must say that this Antragsart is
not available. The wizard must not choose a type of its own in this case.

Reason: A link stays in mails and on web pages after the type was taken out of use. The user
then picks another type instead of a blank page or a wrong form.

Test: The wizard test opens `/apply/<unknown key>` and checks the URL, the step and the toast.
