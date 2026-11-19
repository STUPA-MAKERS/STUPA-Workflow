---
id: "001354"
title: Every button of the app stands in a button group
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/button-group.templates.spec.ts:ButtonGroupTemplates"
implementation:
  - frontend/vendor/ui-kit/src/lib/button-group/button-group.component.ts
  - frontend/vendor/ui-kit/src/styles/button-group.scss
  - frontend/vendor/ui-kit/src/lib/side-sheet/side-sheet.component.html
  - frontend/src/app/
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Every button of the app stands in a button group

Each button of the app (`app-button`, a link or a button with `appButton`, the menu button
`app-row-menu`) must stand in the button group component `app-button-group`, or in a slot that
the kit draws as a group: the actions of a page head, of a detail head and of the bar of the
list/detail layout, the footer of a dialog and the head of a side sheet. Buttons that stand
next to each other must be one group. A single button must be a group of one. The group has
the look of 001350, 001351 and 001353 in each place: a row of a list, a card, a form, an
empty state, a dialog body and a head.

A group of small buttons is as high as a small button. A group of full-width buttons fills
its row, and its buttons share the width equally. A group that holds a main action (a filled
button) keeps the accent fill of that button (001353).

The chrome of the shell (the rail, the bottom bar and the account menu) and the controls
inside a kit component (a text field, a date picker, the toolbar of the Markdown editor) are
not buttons of the app in this sense.

Reason: One shape for every button lets a person find the actions of a screen at a glance,
and one component holds that shape in one place.

Test: `button-group.templates.spec.ts` reads every template of the app and fails for each
button outside a group.
