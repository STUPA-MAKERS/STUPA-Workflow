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
  - frontend/vendor/ui-kit/src/lib/row-menu/row-menu.component.scss
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.scss
  - frontend/vendor/ui-kit/src/lib/list-item/list-item.component.scss
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
editor and a chat composer are input fields too. Every button with a label (filled, tonal,
outlined and text buttons, pill buttons such as a picker, and floating action buttons (FAB)) must be black
on yellow with a black 2 px edge and no yellow outside the edge. A destructive button must be
dark red on yellow with a dark red edge. A pressed toggle button must be yellow on black. The
chosen option of a segmented control must be black on yellow with the same edge. A filter chip must be black on yellow with the same edge, and an active filter
chip yellow on black. In a menu, a list of options and every other list, the chosen or current
row (for example the open item of a list page) must be black on yellow with the same edge; the
other rows stay as they are. A selected table row is black on yellow without the edge. A check box that a component draws itself reads the
same yellow box and black mark. An icon button
without a surface stays as it is. The focused element
must have a double ring: 3 px black next to it and 3 px yellow outside the black. The error
edge must stay visible on the yellow. This applies in both themes. The
switch is off by default, because no system setting asks for it.

Reason: A person with low vision or with a cognitive impairment must find the fields of a
form at a glance.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
