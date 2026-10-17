---
name: empty-state-convention
description: canonical empty state = shared app-empty-state; ghost rows only for lists (shape per list, full width), plain for panes/404/admin
metadata:
  node_type: memory
  type: project
---

Every "nothing here" state is `<app-empty-state>` (`frontend/src/app/shared/ui/empty-state/`).
It has two looks (Frederik, 2026-10-17: "Ich meinte für Listen!"):

- **List** (default): an empty list or a search without a match. Faint aria-hidden ghost rows
  in the shape of the real rows, the message centred over them. The ghost block takes the
  full width and the row geometry of the list it replaces (min-height 4rem, padding
  `10px var(--space-4)`, 2px gap, outer corners `--radius-lg`); never a narrow island.
- **`plain`**: a pane or page that is not a list: detail pane with nothing open, 404 / not
  found, the /admin start, a forbidden pane. No ghosts; an `icon` (ui-kit name) above a
  large heading.

`shape` makes the ghosts mirror the real rows; never the radio look for a list without radios:
`row` (default: title, sub, chip), `choice` (radio pickers in dialogs), `person` (avatar),
`date` (date badge), `agenda` (number), `file`, `table` (data tables), `card` (to-do tiles),
`chat`, `text` (prose). A page whose rows change by width binds it (`[shape]="phone() ? 'row' : 'table'"`).

- `[heading]` = the message. `[body]` only for an existing short line; no helper text.
- One way on is projected as `<app-button variant="tonal" size="sm">` (reset filters, as
  free text, back).
- `rows` = ghost rows, default 5; 3 in sheets, side panes, small dialogs; 2 in tiles; 1 for
  a per-board or per-group line.
- `fill` when it is the only content of a flex-column pane or page: it centres vertically
  and renders the heading as `h2`. Otherwise the heading is a `<p>`; `level` (1–3) sets it explicitly.
- Render it in the `@else` of the list, never as an `<li>` or table row; a data table drops
  `[emptyText]` and renders only while loading or with rows.
- A list beside a detail pane gets the ghost rows itself; the detail pane is `plain`.
- Not for: no-option lines in dropdowns/popovers, inline field values, errors, loading text,
  the desktop Kanban columns (drop zones).

**Why:** pages had drifted into corner notes, framed cards and icon blocks. **How to apply:**
any new list or pane uses this component; never style a bare empty `<p>`.
