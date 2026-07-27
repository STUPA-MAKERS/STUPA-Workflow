---
name: work-autonomously
description: User wants full-auto execution. Pause only to ask through the question tool
metadata:
  node_type: memory
  type: feedback
---

Work in **full auto**. Run backlog items end to end: implement, build, test, commit, push.
Do not pause for a confirmation or for a status check-in. Stop only when a decision truly
blocks you. Then use the AskUserQuestion tool, not a prose question that waits.

**Why:** The user changed the process explicitly. Translated from German: "Pause only when
you have questions, and then use the question tool. Otherwise full auto." A status summary
that waits for "continue" wastes the time of the user.

**How to apply:** Do not end a turn with a "Next: X or Y?" pick-a-direction prompt. Pick the
next item and do it. Batch related fixes, commit per logical unit, and push. Still honor
[[track-side-requests]]: a to-do plus a memory entry for every casual request. Give a short
recap only after a large chunk lands, then continue at once. See
[[ui-patterns-and-backlog2]], [[antragsplattform-backlog]].
