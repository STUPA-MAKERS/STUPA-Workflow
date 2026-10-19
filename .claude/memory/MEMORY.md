# Project memory index

Project-local mirror of the maintainer's working memory for **STUPA-Workflow**. Each entry is
one file that holds one durable fact (a convention, a decision, a data shape, a gotcha). Read the
linked file before you start related work. A `[[slug]]` marker inside a file points at a
sibling memory here.

> **Note:** this repo deliberately does **not** mirror the internal security-audit findings.
> They live only in the maintainer's private memory. Do not add them here.

## How to work on this repo

- [nix-dev-shells](nix-dev-shells.md) — run every dev command in `nix develop .#<component> -c …`, never hand-patch LD_LIBRARY_PATH
- [run-integration-before-push](run-integration-before-push.md) — `pytest` deselects integration; run `-m integration` too, the suite shares one Postgres
- [admin-domain-rules](admin-domain-rules.md) — admin holds all rights, vote delegation per Gremium, every i18n value editable in EN too, memberships and roles only from OIDC groups
- [crud-completeness-rules](crud-completeness-rules.md) — full CRUD behind a permission; the five entities that stay immutable on purpose

## UI / frontend conventions

- [mobile-view-decisions](mobile-view-decisions.md) — 768px, additive media queries, phone bottom bar + "Mehr" sheet, bottom inset, footer rule, PWA bar colours
- [empty-state-convention](empty-state-convention.md) — `app-empty-state` with ghost rows for lists, `plain` for panes, searches and missing records
- [no-uuids-in-ui](no-uuids-in-ui.md) — never show raw UUIDs or ids in the UI, resolve to names server-side (`auth/identity.py`)
- [loading-bar-convention](loading-bar-convention.md) — loading bar counts GETs only; `skipLoading()` / `quietly()` for background reads, mutations never count
- [tailwind-preflight-off-borders](tailwind-preflight-off-borders.md) — preflight OFF: borders need a style, single-side borders need `border-0` first
- [ng-build-budgets](ng-build-budgets.md) — run `npm run build` after CSS or template changes; jest+tsc miss the style budget and the strict-template check

## Data shapes & behaviour

- [positions-field-shape](positions-field-shape.md) — Kostenaufstellung/positions answer: offers = {label,value,preferred}, exactly one preferred, optional noOffers
- [revert-feature-scope](revert-feature-scope.md) — audit-log revert covers config+status+budget/bookings; deletes and assign/move excluded; per-domain permissions
