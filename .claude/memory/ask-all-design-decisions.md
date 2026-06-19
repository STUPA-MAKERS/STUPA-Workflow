---
name: ask-all-design-decisions
description: ask before EVERY design decision; no assumptions; ask mid-implementation too
metadata: 
  node_type: memory
  type: feedback
---

ASK before every design decision — UI/UX, naming, wording, layout, defaults, data shape,
API surface, library choice, anything with more than one reasonable answer. Make NO
assumptions. If a question or ambiguity comes up DURING implementation, stop and ask too —
don't guess and keep going.

**Why:** the user has specific opinions and several of my guesses this session were wrong
(empty-state direction, breadcrumb/header alignment twice). Cheaper to ask than to ship a
wrong guess and iterate.

**How to apply:** use the AskUserQuestion tool with concrete options (and ASCII/code
previews when comparing layouts). This REFINES [[work-autonomously]]: still execute
autonomously once a decision is made, but the pause-for-decision bar is now LOW — when in
doubt, ask. Mechanical/obvious-correct steps (the exact token a utility maps to, a typo
fix) still don't need asking; genuine forks always do.
