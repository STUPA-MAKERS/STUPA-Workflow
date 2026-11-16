---
id: "001170"
title: The chosen Antragsart stands in the apply URL
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/features/apply/apply-wizard.component.spec.ts:ApplyWizardComponent"
implementation:
  - frontend/src/app/app.routes.ts
  - frontend/src/app/features/apply/apply-wizard.component.ts
scope:
  - frontend/src/app/features/apply
  - frontend/src/app/app.routes.ts
---

# The chosen Antragsart stands in the apply URL

The type step of the apply wizard must have the URL `/apply`. When the user presses "Weiter" on
the type step, the URL must change to `/apply/<key>`, where `<key>` is the key of the chosen
Antragstyp. Every later step must keep this URL. A link to `/apply/<key>` must open the wizard
with that type chosen and on the first step after the type step. When this tab holds an autosave
of that type, the wizard must open on the step of the autosave instead. "Zurück" to the type step
and the browser back button must lead to `/apply` with the type still chosen. A reload must keep
the type.

Reason: A Gremium can send a link that opens one Antragsart directly, for example on its web
page or in a mail. The key of a type does not change after the create, so such a link stays
valid when the name of the type changes.

Test: The wizard tests check the URL after "Weiter" and the step that `/apply/<key>` opens.
