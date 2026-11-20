---
id: "001960"
title: Every button of a confirm row is as high as a control
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/vendor/ui-kit/src/styles/button-group.scss
  - frontend/vendor/ui-kit/src/lib/range-chip
  - frontend/src/app/confirm-row.templates.spec.ts
  - frontend/src/app/features/meetings/calendar-subscribe
  - frontend/src/app/features/voting/ballot
  - frontend/src/app/pages/todos/board-settings
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit/src/
---

# Every button of a confirm row is as high as a control

The action group at the end of a dialog, a bottom sheet, a popover or an inline form is a
confirm row: the footer of `app-dialog` or an `app-button-group` with `[main]="true"`. Every
button in a confirm row must be exactly as high as a control (`--control-height`, 40px), on the
phone and on the desktop. This includes a button with `size="sm"` or `size="lg"`, a block button
and a copy button. The kit sets the height, the padding and the font size of the buttons of the
group, so a page cannot make one footer lower or higher than another.

An app template must not set `size` on a button in a confirm row. A button group in an element
whose class names a foot (`__foot`, `…Foot`, `__footer`) must be a confirm row.

The floating main action of a page or a form sheet (FAB, 000198) is not a confirm row and keeps
its size. A button beside a field takes the height of the field (001910).

Reason: Footers of different heights (32px in one popover, 40px in a dialog, 52px under the
ballot) make the same action look different from one dialog to the next.

Test: `frontend/src/app/confirm-row.templates.spec.ts` finds a sized button in a confirm row and a
foot group that is not a confirm row. `button-group.component.spec.ts` of the kit asserts the
rule. Screenshot review on the phone and on the desktop, light, dark and very high contrast.
