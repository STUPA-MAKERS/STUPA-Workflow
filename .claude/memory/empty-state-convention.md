---
name: empty-state-convention
description: canonical empty state = shared app-empty-state with ghost rows; rules for rows, fill and the one way on
metadata:
  node_type: memory
  type: project
---

Every "nothing here" state (empty list, search without a match, nothing selected, missing
record, no access) is `<app-empty-state>` (`frontend/src/app/shared/ui/empty-state/`). It
draws faint aria-hidden ghost rows in the shape of list rows and centres the message over
them. It is the "Geister-Zeilen" state of the "TOP hinzufügen" dialog (Frederik's pick,
2026-10-17: "überall einheitlich, Vorbild Ghost-Variante").

- `[heading]` = the message. `[body]` only for an existing short line; no helper text.
- One way on is projected as `<app-button variant="tonal" size="sm">` (reset filters, as
  free text, back).
- `rows` = ghost rows, default 5; 3 in sheets, side panes, small dialogs; 2 in tiles; 1 for
  a per-board or per-group line.
- `fill` when it is the only content of a flex-column pane or page: it centres vertically
  and renders the heading as `h2`. Otherwise the heading is a `<p>`; `level` (1–3) sets it explicitly.
- Render it in the `@else` of the list, never as an `<li>` or table row; a data table drops
  `[emptyText]` and renders only while loading or with rows.
- Not for: no-option lines in dropdowns/popovers, inline field values, errors, loading text,
  the desktop Kanban columns (drop zones).

**Why:** pages had drifted into corner notes, framed cards and icon blocks. **How to apply:**
any new list or pane uses this component; never style a bare empty `<p>`.
