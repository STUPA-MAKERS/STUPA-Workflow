---
name: tailwind-preflight-off-borders
description: preflight is OFF, so single-side border utilities leak the medium initial width
metadata: 
  node_type: memory
  type: reference
---

Tailwind `preflight` is OFF in this repo (`tailwind.config.js`). This avoids the global h1,
button and ul resets. Borders pay for it. There is NO `*{ border-width:0 }` reset, so the
INITIAL `border-width` is `medium` (about 3px) and `border-style` defaults to `none`.

Two traps hit the SCSS to Tailwind migration:
1. A border width without a style is invisible. Always add `border-solid` or `border-dashed`,
   for example `border border-solid border-line`. Commit 5a45ff3 already handles this.
2. A SINGLE-SIDE border (`border-b`, `border-t`, `border-l-2` and so on) sets the width of
   THAT side only. The other sides keep the `medium` (about 3px) initial width. `border-solid`
   plus `border-line` then make all four sides solid and colored. The result is fat 3px
   borders on the wrong sides. FIX: prefix `border-0`, which zeros all sides. Tailwind emits
   `.border-0` BEFORE the side utilities, so the single-side width still wins:
   `border-0 border-b border-solid border-line`. Commit 8bf6c06 fixed 12 usages.

A full `border` or `border-2` is fine, because it sets all sides. Any single-side border
MUST include `border-0`. Related: [[empty-state-convention]]. The config is
`frontend/tailwind.config.js`.
