---
name: tailwind-preflight-off-borders
description: Tailwind preflight is OFF, so a border utility needs a border style, and a single-side border needs border-0 first
metadata:
  node_type: memory
  type: reference
---

Tailwind `preflight` is OFF (`frontend/tailwind.config.js`, `corePlugins.preflight: false`),
so Tailwind does not reset h1, button, ul and the other elements globally. Borders pay for it:
there is no `* { border-width: 0 }` reset. The initial `border-width` is `medium` (about 3px)
and the initial `border-style` is `none`.

Two traps:

1. A border width without a style is invisible. Always add `border-solid` or `border-dashed`,
   for example `border border-solid border-line`.
2. A SINGLE-SIDE border (`border-b`, `border-t`, `border-l-2` …) sets the width of THAT side
   only. The other sides keep the `medium` initial width, and `border-solid` plus `border-line`
   then draw all four sides, about 3px thick on the wrong sides. Fix: put `border-0` first,
   which zeros all sides. Tailwind emits `.border-0` before the side utilities, so the
   single-side width still wins: `border-0 border-b border-solid border-line`.

A full `border` or `border-2` is fine, because it sets all four sides.
