---
id: "000598"
title: Very high contrast highlights the fields black on yellow
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedFields"
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedButtons"
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedChips"
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedChosenRow"
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:highlightedCurrentRow"
  - "frontend/src/app/shared/highlighted-fields.styles.spec.ts:highlightedFields"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/styles/_field.scss
  - frontend/vendor/ui-kit/src/styles/_check.scss
  - frontend/vendor/ui-kit/src/lib/button/button.component.scss
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.scss
  - frontend/vendor/ui-kit/src/lib/select/select.component.scss
  - frontend/vendor/ui-kit/src/lib/filter-select/filter-select.component.scss
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.scss
  - frontend/vendor/ui-kit/src/lib/list-item/list-item.component.scss
  - frontend/vendor/ui-kit/src/lib/row-menu/row-menu.component.scss
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/vendor/ui-kit/src/lib/toast/toast-bar.component.scss
  - frontend/vendor/ui-kit/markdown-editor/src/markdown-editor.component.scss
  - frontend/vendor/ui-kit/src/lib/badge/badge.component.scss
  - frontend/vendor/ui-kit/src/lib/seg-bar/seg-bar.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Very high contrast highlights the fields black on yellow

While "Sehr hoher Kontrast" is on (000605), every input field (text, text area, select, date,
time, amount and search field) must have a yellow fill, black text, a black label, a black
placeholder and black icons. A Markdown editor, a chat composer and the check box "Ich bin kein
Roboter" (ALTCHA) are input fields too. In the protocol, the whole rounded pane of the TOP is
the field, without inner boxes. Every button with a label and every icon button must have a
yellow fill and black content. This includes the floating action button (FAB), the buttons of the
meeting dock, a tool of the editor and the button in a file drop area. A destructive button
must be dark red on yellow. A toast and the toast bar must be black on yellow. A tag (for
example "NÖ") is a black plate with yellow text. A progress bar is a yellow plate with black
parts. The focused element must have a double ring: 3 px black next to it and 3 px yellow
outside the black. The error edge must stay visible on the yellow.

The rules 000615 to 000620 control a choice, the navigation, a menu, a row, a switch, a
checkbox and a radio button.

Reason: A person with low vision or with a cognitive impairment must find the fields of a
form at a glance.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
