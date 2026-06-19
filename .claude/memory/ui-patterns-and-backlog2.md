---
name: ui-patterns-and-backlog2
description: "Second-wave UI requirements/patterns for the antragsplattform admin (dialogs, typeahead, dropdowns)"
metadata: 
  node_type: memory
  type: project
---

Recurring UI rules + open work (tasks #18–#20, plus #13/#14/#16), branch `feat/admin-ux-flow-editor-fixes`:

- **Add via DIALOG, not inline-above-the-list — enforce everywhere** (#19). Applies to gremien members, budget tree nodes, user role-add, etc.
- **Search = inline typeahead** (suggestions render directly under the search field; click adds). Separate result dropdowns are "müll" (#18).
- **Constrained values = dropdowns** (CD-Variante, etc.), never free text. **Slugs auto-generate** from the name (#18).
- **Per-entity management = its own subpage** (e.g. each Gremium → its own members-table subpage), not an inline panel (#18).
- **No Expert/Simple split in the flow editor** — fold everything into one mode (#20). Flow **templates must be savable** (save current graph as a reusable preset). Add inline help explaining terms like "Akteur"/guards (#20).
- **Everything is a SHARED component** (#26) — no page-local table/dialog/button markup. Build a capable shared data-table (columns, custom cell templates, tree indentation, row actions) in `shared/ui` and migrate all bespoke tables (users, gremien, gremium-members, budget-tree, budget-dashboard, admin-home forms, meetings). DialogComponent/ButtonComponent/SelectComponent already exist; reuse them everywhere. **AG-Grid decided AGAINST**: Community bundle is heavy and not token-aligned; tree-data/row-grouping are Enterprise-only. In-house shared table is the call.
- **Meetings (#27)**: "Sitzung anlegen" as a dialog; the Sitzungen list as the shared table.
- **Table display conventions**: boolean columns render a colored ✓/✗ (success/danger), narrow width — not a badge/word. Expandable/clickable rows need a visible cue (rotating chevron per row). All rows uniform height (shared DataTable forces 3rem) — action-button rows must not be taller than button-less rows.
- **Form builder (#13)**: admin tile "Anträge" → list of Antragstypen/Forms (add via dialog) → edit each like **Nextcloud Forms** (title+md description, "+ Add a question" type menu: checkboxes/radio/dropdown/file/short answer/long text/date/time/linear scale/color; per-question title+description+options+drag-reorder+required+⋯; View/Edit toggle).

See [[admin-domain-rules]], [[nextcloud-parity-ui]], [[antragsplattform-backlog]].
