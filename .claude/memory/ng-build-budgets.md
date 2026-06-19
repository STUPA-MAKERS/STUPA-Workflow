---
name: ng-build-budgets
description: Frontend has ng build bundle/style budgets that jest+tsc do NOT enforce — run npm run build before deploy
metadata: 
  node_type: memory
  type: feedback
---

`ng build` (the Docker `web` stage, `frontend/npm run build`) enforces **budgets** that `tsc --noEmit` and `jest` do NOT catch. A CSS-heavy component change can pass all local specs/typecheck/eslint and still **fail the Docker build**.

**Why:** angular.json budgets — `anyComponentStyle` errors at **18 kB** per component style block (warns at 12 kB); initial bundle warns at 600 kB. 2026-06-13: a small timeline-CSS addition pushed `meetings.component.ts` styles to 18.07 kB → hard build error (67 bytes over). `meetings.component` styles sit ~17–18 kB, so it's the canary.

**How to apply:** after any non-trivial **component CSS** change (especially meetings.component), run `cd frontend && npm run build` before declaring done / before the user deploys — don't rely on jest+tsc alone. Keep duplicated CSS DRY (e.g. dedupe gradients into a `--var`). Also fixed NG8102 (`?? ''` on `Record` index is flagged) and NG8113 (unused standalone imports) — `ng build` surfaces these as warnings.

**ALSO: `ng build` runs AOT strict-template typecheck that `tsc -p tsconfig.app.json` does NOT.** 2026-06-13: `@if (sig())` does NOT narrow later `sig()` calls in the template — `{{ ... | t: { n: formVersion() } }}` failed (number|null not assignable) until rewritten `@if (formVersion(); as v) { ... { n: v } }`. Rule: for any template change touching nullable signals/i18n params, run `npm run build`, not just jest. Part of [[backlog-2026-06-13]].
