---
id: "000622"
title: A heading that a script focuses shows no focus ring
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:noRingOnScriptFocus"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A heading that a script focuses shows no focus ring

An element that has `tabindex="-1"` and that a script focuses (for example the title of a detail
after it opens) must not show a focus ring. This applies in every display setting, also in "Sehr
hoher Kontrast".

Reason: The script moves the focus so that a screen reader reads the new title. A ring around a
heading looks like an input field.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` expects that the focus rule of
very high contrast excludes `[tabindex='-1']`.
