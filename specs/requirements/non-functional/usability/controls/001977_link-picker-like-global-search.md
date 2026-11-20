---
id: "001977"
title: The link picker looks like the global search
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/todos/link-picker/todo-link-picker.component.html
  - frontend/src/app/features/todos/link-picker/todo-link-picker.component.scss
scope:
  - frontend/src/app/features/todos/link-picker
---

# The link picker looks like the global search

At every width, the "Verknüpfen" picker (spec 001408) must look like the global search (the
command palette of the kit):

1. The panel has the same frosted glass, the same scrim and the same corner radius: the radius
   of the search pill plus its inset, so the corner and the pill keep one even gap.
2. The search field is the search pill of the global search: the height `--control-height-lg`,
   a magnifier of 22px at the start, the accent ring while it has the focus, and the key "Esc"
   (⎋ on Apple devices) at the end. The key is the close button. There is no separate ✕ button.
3. The kind chips under the field stand centred, as the key hints of the global search do.
4. On a phone the picker is the same floating panel, not a bottom sheet. It stands at the top
   of the screen below the safe area, and the close button in the field is a ✕ instead of the
   key, as in the global search.

Reason: The two searches are the same gesture, so they must look the same. A second look for
the same thing makes the person look twice.

Test: The frontend unit test of the picker closes it with the "Esc" key button and with Escape,
and on a phone shows the floating panel with the ✕.
