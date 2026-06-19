---
name: empty-state-convention
description: canonical empty-state = framed card (.empty-state), rendered standalone
metadata:
  node_type: memory
  type: project
---

Canonical list/table empty-state = a FRAMED CARD: `border + border-radius:var(--radius-lg)
+ background:var(--color-surface) + text-align:center + color:var(--color-text-muted) +
padding:var(--space-6)`. Identical on desktop and mobile. Defined as the global
`.empty-state` in `frontend/src/styles/_base.scss`. The reference look is the shared
`<app-data-table>` (`dt--boxed` wrapper + `dt__empty` row) — every other page must match it.

**Render it STANDALONE:** when the collection is empty, HIDE the table and render the
`.empty-state` card in the `@else` branch (e.g. `@if (rows().length) { <table> } @else {
<div class="empty-state">…</div> }`). Do NOT put `.empty-state` as an in-table `@empty`
`<td>` row — that double-frames on desktop (inside the table wrapper) and mis-pads on the
mobile card transform.

**Don't double-frame:** if the empty already sits inside a framed wrapper (a `.card`,
`dt--boxed`), use plain centered-muted text (`text-align:center; color:muted; padding
space-6`) and let the wrapper be the frame — NOT `.empty-state`. grants does this
(`.grants__empty` inside its `.card`).

**Why:** the first pass (2026-06-14) wrongly went borderless and stripped invoices'
`inv__emptyCard` frame → naked text in a `min-height:60vh` void. User confirmed the FRAMED
box (tasks/applications) is the wanted look; corrected to framed standalone card.

Current consumers of `.empty-state`: invoices, expenses, applications-table. data-table
pages (tasks + admin) frame via `dt--boxed`. grants frames via its `.card`. INTENTIONAL
exceptions (not no-results table empties, left alone): budget-dashboard `.bd__empty`
(dashed "create your first budget" onboarding panel, title+body) and meetings sub-panel
empties (`mtg__muted`/`mtg__tocEmpty`, dense 3-pane session UI). invoices keeps
`min-height:60vh` (functional — `.inv__dropOverlay` ZUGFeRD drag-drop needs the relative
parent height), so its card top-aligns with a gap below.

Related: [[mobile-view-decisions]], [[ng-build-budgets]].
