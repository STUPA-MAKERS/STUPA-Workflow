# Project memory index

Project-local mirror of the maintainer's working memory for **STUPA-Workflow**. Each entry is
one file holding one durable fact (a convention, a spec, a status note, a gotcha). Read the
linked file before doing related work. Linked `[[slug]]` markers inside files point at sibling
memories here.

> **Note:** internal security-audit findings are deliberately **not** mirrored into this repo.
> They live only in the maintainer's private memory. Do not re-add them here.

## How to work on this repo (conventions & preferences)

- [work-autonomously](work-autonomously.md) — full-auto execution; only pause via the question tool
- [ask-all-design-decisions](ask-all-design-decisions.md) — ASK before every design decision; no silent assumptions
- [always-track-todos](always-track-todos.md) — always track progress with the todo tool on every task
- [track-side-requests](track-side-requests.md) — track every casual request as a todo + memory
- [repo-ship-workflow](repo-ship-workflow.md) — always finish: branch+commit+push+PR, then watch CI + fix failures
- [python-strong-typing](python-strong-typing.md) — always strongly-typed Python ≥3.13: full annotations, no bare Any
- [admin-domain-rules](admin-domain-rules.md) — admin=all-rights; vote-delegation per-Gremium; edit all i18n values in EN too

## UI / frontend conventions

- [nextcloud-parity-ui](nextcloud-parity-ui.md) — admin UIs (user table, form builder) modeled on Nextcloud
- [ui-patterns-and-backlog2](ui-patterns-and-backlog2.md) — add-via-dialog, typeahead, dropdowns, per-entity subpages, no expert-mode
- [mobile-view-decisions](mobile-view-decisions.md) — mobile pass: hamburger drawer, card tables, vertical stacking, 768px, desktop unchanged
- [empty-state-convention](empty-state-convention.md) — global `.empty-state` utility = one source for all table/list/card empty-states
- [no-uuids-in-ui](no-uuids-in-ui.md) — never show raw UUIDs/ids in UI; resolve to names server-side (`_author_names`)
- [loading-overlay-convention](loading-overlay-convention.md) — overlay = GET-only interceptor + `SKIP_LOADING` token; mutations/polls/typeahead opt out
- [tailwind-preflight-off-borders](tailwind-preflight-off-borders.md) — preflight OFF: single-side borders need `border-0` + `border-solid`
- [ng-build-budgets](ng-build-budgets.md) — run `npm run build` after CSS changes; jest+tsc miss the bundle/style budget that fails Docker

## Data shapes & tech gotchas

- [positions-field-shape](positions-field-shape.md) — Kostenaufstellung/positions field: offers = {label,value,preferred}, exactly one preferred
- [alembic-revision-id-limit](alembic-revision-id-limit.md) — alembic revision ids MUST be ≤32 chars (alembic_version varchar(32))
- [revert-feature-scope](revert-feature-scope.md) — audit-log revert covers config+status+budget/bookings; deletes & assign/move excluded

## Feature specs & designs

- [budget-kostenstellen-spec](budget-kostenstellen-spec.md) — hierarchical budgets: VS-800-40 naming, roll-down available / roll-up consumed
- [budget-tab-redesign](budget-tab-redesign.md) — Budget tab: left Budget→Year tree, stacked pies, Beantragt col, cost-centre colors, URL sync
- [budget-import-zugferd](budget-import-zugferd.md) — ZUGFeRD/Factur-X expense import; drag-into-window + drop-overlay
- [flow-engine-redesign](flow-engine-redesign.md) — guard catalog + compare guard, 3 actions (webhook/notify/addToNextSession), 16-perm rework
- [sessions-protokollant-redesign](sessions-protokollant-redesign.md) — per-meeting protokollant, granular gremium-role perms, 3-pane session view, beamer follow
- [delegation-rework](delegation-rework.md) — delegation sitzungsgebunden + Stellvertreter-Pool
- [invoices-followups-2026-06-13](invoices-followups-2026-06-13.md) — beleg URL / manual-attach / centering / booking-prefill follow-ups
- [be-fe-field-gaps-2026-06-13](be-fe-field-gaps-2026-06-13.md) — backend fields not yet exposed in the frontend (GroupMapping/MailTemplate/display gaps)

## Backlogs & status snapshots (time-stamped, partly DONE)

- [antragsplattform-backlog](antragsplattform-backlog.md) — broad feature backlog + meetings/flow overhaul history
- [backlog-2026-06-11](backlog-2026-06-11.md) — DONE + merged to local main; push + migrations 0014–0018 + stack rebuild pending
- [backlog-2026-06-13](backlog-2026-06-13.md) — ~20-item session; branch fix/gremium-member-perms
- [backlog-2026-06-14b](backlog-2026-06-14b.md) — 8-item backlog: PWA name, fades, fuzzy search, backend filters, perms, pre-fills, CSS
- [flow-engine-bug-fixes](flow-engine-bug-fixes.md) — DONE: flow + project-wide fixes, typing/lint/tests zeroed, merged to main
- [async-protocol-render](async-protocol-render.md) — DONE: async protocol PDF render; stack rebuild + migration pending
