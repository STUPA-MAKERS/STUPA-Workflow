---
name: empty-state-convention
description: canonical empty-state = framed card (.empty-state), rendered standalone
metadata:
  node_type: memory
  type: project
---

Canonical list/table empty-state = a FRAMED CARD: `border + border-radius:var(--radius-lg)
+ background:var(--color-surface) + text-align:center + color:var(--color-text-muted) +
padding:var(--space-6)`. It looks identical on desktop and mobile. The global `.empty-state`
in `frontend/src/styles/_base.scss` defines it. The reference look is the shared
`<app-data-table>` (`dt--boxed` wrapper + `dt__empty` row). Every other page must match it.

**Render it STANDALONE:** when the collection is empty, HIDE the table and render the
`.empty-state` card in the `@else` branch (e.g. `@if (rows().length) { <table> } @else {
<div class="empty-state">…</div> }`). Do NOT put `.empty-state` as an in-table `@empty`
`<td>` row. Such a row double-frames on desktop, inside the table wrapper, and mis-pads on
the mobile card transform.

**Do not double-frame:** when the empty already sits inside a framed wrapper (a `.card`,
`dt--boxed`), use plain centered muted text (`text-align:center`, `color:muted`,
`padding:space-6`) and let the wrapper be the frame. Do NOT use `.empty-state`. grants
follows this rule with `.grants__empty` inside its `.card`.

**Why:** the first pass (2026-06-14) wrongly went borderless and stripped the
`inv__emptyCard` frame from invoices. That left naked text in a `min-height:60vh` void. The
user confirmed the FRAMED box (tasks and applications) as the wanted look. The convention is
now a framed standalone card.

Current consumers of `.empty-state`: invoices, expenses, applications-table. The data-table
pages (tasks and admin) frame through `dt--boxed`. grants frames through its `.card`.
INTENTIONAL exceptions, left alone because they are not no-results table empties:
budget-dashboard `.bd__empty` (a dashed "create your first budget" onboarding panel with a
title and a body) and the meetings sub-panel empties (`mtg__muted` and `mtg__tocEmpty`, the
dense 3-pane meeting UI). invoices keeps `min-height:60vh` for a functional reason: the
`.inv__dropOverlay` ZUGFeRD drag-drop needs the relative parent height. So its card
top-aligns and leaves a gap below.

Related: [[mobile-view-decisions]], [[ng-build-budgets]].
