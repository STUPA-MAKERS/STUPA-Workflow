---
id: "002570"
title: Every icon of a button group has one size and one colour
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
tests:
  - "frontend/vendor/ui-kit/src/lib/button-group/button-group.component.spec.ts:ButtonGroupComponent"
implementation:
  - frontend/vendor/ui-kit/src/styles/button-group.scss
scope:
  - frontend/vendor/ui-kit
---

# Every icon of a button group has one size and one colour

In a connected button group (`app-button-group` and the action slots of the heads of the kit),
every icon must have the same size: 18px, also in a group of small buttons. This applies to the leading icon of a button with a label, to a button with only
an icon, to the trigger of a row menu and to an icon that the page gives a `size`. Every icon
of an unselected button must have the text colour of the group
(`--color-on-accent-container`), also when the button has the look `text`. A selected,
disabled or destructive button keeps its own colour, and very high contrast keeps its look.

Reason: In the Anwesenheit of a Gremium, the export as XLSX (a label with a 16px icon) and the
export as CSV (only a 20px icon) stand in one group. The icon button was larger and grey,
because the grey glyph of a text icon button tied with the colour of the group, and the
two download icons looked broken side by side (Frederik 2026-11-23). Frederik chose 18px over 20px.

Test: The tests of the button group check the size variable of the group, the size on every
icon and the colour of a text icon button in a group. A person checks the look on screenshots
in both themes and in the display settings.
