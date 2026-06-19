---
name: tailwind-preflight-off-borders
description: preflight is OFF — single-side border utilities leak the medium initial width
metadata: 
  node_type: memory
  type: reference
---

Tailwind `preflight` is OFF in this repo (tailwind.config.js, to avoid global h1/button/ul
resets). Consequence for borders: there is NO `*{ border-width:0 }` reset, so the INITIAL
`border-width` is `medium` (~3px), and `border-style` defaults to `none`.

Two gotchas (both bit the SCSS→Tailwind migration):
1. A border width without a style is invisible — always add `border-solid` / `border-dashed`
   (e.g. `border border-solid border-line`). Already handled in commit 5a45ff3.
2. A SINGLE-SIDE border (`border-b`/`border-t`/`border-l-2` …) only sets THAT side's width;
   the other sides keep the `medium` (~3px) initial width, and `border-solid`+`border-line`
   make all four sides solid+coloured → fat 3px borders on the wrong sides. FIX: prefix
   `border-0` (zeros all sides; Tailwind emits `.border-0` BEFORE the side utilities, so the
   single-side width still wins): `border-0 border-b border-solid border-line`. Fixed across
   12 usages in commit 8bf6c06.

So: full `border`/`border-2` = fine (sets all sides). Any single-side border = MUST include
`border-0`. Related: [[empty-state-convention]], the config is `frontend/tailwind.config.js`.
