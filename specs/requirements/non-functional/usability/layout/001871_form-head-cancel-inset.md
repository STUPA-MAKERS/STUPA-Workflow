---
id: "001871"
title: The label of "Abbrechen" in a form head ends at the side inset
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/shared/ui/pane-form/pane-form.component.spec.ts:FormBar"
implementation:
  - frontend/src/app/shared/ui/_form-bar.scss
scope:
  - frontend/src/app/
---

# The label of "Abbrechen" in a form head ends at the side inset

In the head bar of a form (001870), the label of "Abbrechen" must end as far from the end edge
as the icon starts from the start edge. The text button has 12px around its label, so its pill
stands 12px closer to the edge than the icon: 20px in a pane, where the icon has 32px.

This is the rule of 001341 for the close button of a dialog, applied to a text button.

Reason: The pill of "Abbrechen" stood 32px from the edge, so its label ended 44px from the edge
and the button looked pushed inward against the icon at 32px.

Test: A unit test reads the style of the bar and expects the end padding to be the side inset
less the 12px of the text button.
