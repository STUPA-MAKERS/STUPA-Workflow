---
name: ask-all-design-decisions
description: ask before EVERY design decision, make no assumptions, ask mid-implementation too
metadata: 
  node_type: memory
  type: feedback
---

ASK before every design decision — UI/UX, naming, wording, layout, defaults, data shape, API
surface, library choice, anything with more than one reasonable answer. Make NO assumptions. If a
question or an ambiguity comes up DURING implementation, stop and ask as well. Do not guess and
keep going.

**Why:** the user has specific opinions, and several of my guesses this session were wrong
(empty-state direction, breadcrumb/header alignment twice). To ask is cheaper than to ship a wrong
guess and iterate.

**How to apply:** use the AskUserQuestion tool with concrete options. Add ASCII or code previews
when you compare layouts. This REFINES [[work-autonomously]]: after a decision, still execute
autonomously, but the pause-for-decision bar is now LOW. When in doubt, ask. A mechanical step
with one obviously correct answer still needs no question, for example the exact token a utility
maps to or a typo fix. A genuine fork always needs one.
