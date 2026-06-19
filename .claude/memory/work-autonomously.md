---
name: work-autonomously
description: User wants full-auto execution; only pause to ask via the question tool
metadata:
  node_type: memory
  type: feedback
---

Work in **full auto**: keep executing backlog items end-to-end (implement → build → test → commit → push) without pausing for confirmation or status check-ins. Only stop when genuinely blocked on a decision — and then use the AskUserQuestion tool, not a prose question that waits.

**Why:** User explicitly changed the process ("Pausiere nur, wenn du fragen hast und dann verwende das fragen-tool. Ansonsten Full Auto"). Status summaries that wait for "continue" waste their time.

**How to apply:** Don't end turns with "Next: X or Y?" pick-a-direction prompts. Pick the next item and do it. Batch related fixes, commit per logical unit, push. Still honor [[track-side-requests]] (todo + memory for every casual request). Surface a brief recap only after a substantial chunk lands, then immediately continue. See [[ui-patterns-and-backlog2]], [[antragsplattform-backlog]].
