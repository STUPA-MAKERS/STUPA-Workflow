---
id: "001360"
title: An empty list shows a face in a ring of dots
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.spec.ts:EmptyStateComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.ts
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.html
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.scss
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# An empty list shows a face in a ring of dots

An empty state that is not `plain` must show a flat face above its message: two eyes with
pupils and a slightly bent mouth, with no outline, in a ring of small round dots at different
distances from the centre. This applies to an empty list, a search without a hit, an empty
section of a detail, a small tile and a list in a dialog. The face replaces the ghost rows.

- In the list column of a list-detail page (`.ld-pane`) the face must be large (132 px wide)
  and centred in the free height of the column.
- Everywhere else the face must be small (88 px wide) and the block keeps its own height.
- Below the face, the message must be a small muted hint: a crossed-out lens icon
  (`searchOff`) and the heading on one line. The body does not show.
- The face is decoration. It must be hidden from the screen reader.

A `plain` state (nothing open in a detail pane, a missing record, a page without access) shows
no face, only a muted icon above the message (001361 says how the face moves). Dropdown no-hit
lines, inline values, errors and the desktop Kanban columns must have no empty state.

Reason: Ghost rows look like a list that is still loading. A face says at once that the list is
empty, and the quiet hint keeps the page calm.

Test: A unit test renders the empty state and expects the face, hidden from the screen reader,
and the hint with the heading. A second test with `plain` expects no face.
