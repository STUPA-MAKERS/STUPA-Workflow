---
id: "000598"
title: Highlighted fields have black text on yellow
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedFields"
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedButtons"
  - "frontend/src/app/shared/highlighted-fields.styles.spec.ts:highlightedFields"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/styles/_field.scss
  - frontend/vendor/ui-kit/src/styles/_check.scss
  - frontend/vendor/ui-kit/src/lib/button/button.component.scss
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.scss
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Highlighted fields have black text on yellow

With the switch "Eingabefelder hervorheben" on (000593), every input field (text, text area,
select, date, time, amount and search field) must have a yellow background, black text, a black
label, a black placeholder, black icons and a 2 px black edge. Every checkbox, radio button and
switch must have a yellow box with a 2 px black edge, and its mark must be black. A Markdown
editor and a chat composer are input fields too. Every button with a surface (filled, tonal and
outlined buttons, pill buttons such as a picker, and floating action buttons (FAB)) must be black
on yellow with a black 2 px edge and no yellow outside the edge. A destructive button must be
dark red on yellow with a dark red edge. A pressed toggle button must be yellow on black. The
chosen option of a segmented control must be black on yellow with the same edge. A text button
and an icon button without a surface stay as they are. The focused element
must have a double ring: 3 px black next to it and 3 px yellow outside the black. The error
edge must stay visible on the yellow. This applies in both themes. The
switch is off by default, because no system setting asks for it.

Reason: A person with low vision or with a cognitive impairment must find the fields of a
form at a glance.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
