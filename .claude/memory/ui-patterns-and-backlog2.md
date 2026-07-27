---
name: ui-patterns-and-backlog2
description: Second-wave UI patterns for the antragsplattform admin (dialogs, typeahead, dropdowns)
metadata: 
  node_type: memory
  type: project
---

Recurring UI rules and open work (tasks #18–#20, plus #13, #14, #16), branch
`feat/admin-ux-flow-editor-fixes`:

- **Add through a DIALOG, not inline above the list. Enforce this everywhere** (#19). It
  applies to Gremium members, budget tree nodes, the user role-add, and so on.
- **Search is an inline typeahead.** Suggestions render directly under the search field, and
  a click adds the entry. The user rejects a separate result dropdown as garbage (#18).
- **Constrained values use dropdowns** (CD variant and so on), never free text. **Slugs
  generate automatically** from the name (#18).
- **Each entity gets its own management subpage.** For example, each Gremium gets its own
  members-table subpage, not an inline panel (#18).
- **No Expert/Simple split in the flow editor.** Fold everything into one mode (#20). Flow
  **templates must be savable**, so the user can save the current graph as a reusable preset.
  Add inline help that explains terms such as "Akteur" (actor) and guards (#20).
- **Everything is a SHARED component** (#26). No page-local table, dialog or button markup.
  Build one capable shared data table in `shared/ui` with columns, custom cell templates,
  tree indentation and row actions. Then migrate all bespoke tables: users, gremien,
  gremium-members, budget-tree, budget-dashboard, admin-home forms and meetings.
  DialogComponent, ButtonComponent and SelectComponent already exist. Reuse them everywhere.
  **AG-Grid is ruled out**: the Community bundle is heavy and not token-aligned, and
  tree-data and row-grouping are Enterprise-only. The in-house shared table wins.
- **Meetings (#27)**: create a meeting ("Sitzung anlegen") through a dialog. Render the
  meeting list with the shared table.
- **Table display conventions**: a boolean column renders a colored ✓ or ✗ (success or
  danger) at a narrow width, not a badge or a word. An expandable or clickable row needs a
  visible cue, which is a rotating chevron per row. All rows keep a uniform height, because
  the shared DataTable forces 3rem. A row with action buttons must not be taller than a row
  without buttons.
- **Form builder (#13)**: the admin tile for applications ("Anträge") opens a list of
  application types and forms, where a dialog adds a new one. Edit each one like **Nextcloud
  Forms**: a title plus a Markdown description, and a "+ Add a question" type menu with
  checkboxes, radio, dropdown, file, short answer, long text, date, time, linear scale and
  color. Each question carries a title, a description, options, drag-reorder, a required flag
  and a ⋯ menu. A View/Edit toggle switches the mode.

See [[admin-domain-rules]], [[nextcloud-parity-ui]], [[antragsplattform-backlog]].
