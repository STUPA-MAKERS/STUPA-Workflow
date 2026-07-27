---
name: track-side-requests
description: User wants every casual side request tracked as a to-do and written to memory
metadata: 
  node_type: memory
  type: feedback
---

The user said, translated from German: "Track everything that I write to you in passing as a
to-do, and write it to memory."

**Why:** The user sends requirements in many short messages. No requirement may get lost
between turns.

**How to apply:** When the user mentions a new requirement in passing, even mid-task, add it
as a task (TaskCreate) at once. If the requirement or preference is durable, also write it
into a memory file. Do not rely on it staying in the conversation context. See
[[antragsplattform-backlog]].
