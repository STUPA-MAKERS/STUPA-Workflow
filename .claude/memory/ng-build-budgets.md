---
name: ng-build-budgets
description: ng build enforces style budgets and AOT strict-template checks that jest and tsc do not. Run npm run build after CSS or template changes
metadata:
  node_type: memory
  type: feedback
---

`npm run build` (`ng build`) catches two classes of error that `npm run typecheck` (`tsc -p
tsconfig.app.json --noEmit`) and `npm test` (jest) do not. CI (`.github/workflows/ci.yml`) and
the Docker `web` stage (`deploy/web/Dockerfile`) both run the build, so a change can pass every
local spec and still fail there.

1. **Budgets** in `frontend/angular.json`: `anyComponentStyle` warns at 20 kB and errors at
   28 kB per component style; the initial bundle warns at 1 MB and errors at 1.1 MB. A small
   CSS addition to a large component can tip it over the limit.
2. **AOT strict templates** (`strictTemplates: true`). `@if (sig())` does NOT narrow a later
   `sig()` call in the template, so `{{ … | t: { n: formVersion() } }}` fails with
   "number | null is not assignable". Write `@if (formVersion(); as v) { … { n: v } }`. The
   build also warns on NG8102 (`?? ''` on a `Record` index) and NG8113 (unused standalone
   imports).

**How to apply:** after any non-trivial component CSS change, or any template change that
touches nullable signals or i18n params, run `cd frontend && npm run build` before you call the
work done. Keep duplicated CSS DRY (for example, move a repeated gradient into a custom
property) to stay under the style budget.
