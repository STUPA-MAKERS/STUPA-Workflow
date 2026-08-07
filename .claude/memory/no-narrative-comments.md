---
name: no-narrative-comments
description: Comment only what the code cannot say. One line, no essays, no restating the diff
metadata:
  node_type: memory
  type: feedback
---

Write a comment only where the code cannot say the thing itself. Keep it to one line.

**Why:** the user has asked for this twice, in the task brief ("KEINE UNNÖTIGEN KOMMENTARE")
and again after the review of PR #142, where the verdict was blunt: the volume of explanatory
comments is unacceptable. Both the agents and I kept writing three to five line narratives
above one-line changes.

**How to apply:**

- A comment earns its place when it records a NON-OBVIOUS why: a constraint, a trap, a rejected
  alternative that a reader would otherwise re-introduce. One line.
- Never restate what the next line does.
- Never narrate the bug that was fixed, the measurement, or the history. That belongs in the
  commit message and the PR, which is where a reader looks for it.
- Never explain a rejected design in code. The commit message carries it.
- A docstring states what the function does and its contract. It is not the place for the
  reasoning behind a change either.

Bad, and the exact shape to avoid:

    # The document SHAPE belongs to the kind of document, not to the corporate
    # design. One Gremium renders applications and protocols, so the shape has
    # to come from this render path. The design contributes logos only.

Good:

    # Shape comes from the document kind, not the design; the design adds logos.

This applies to every file in the repo and to every subagent brief. State it in the brief, or
the agent writes essays. See [[work-autonomously]].
