---
name: track-side-requests
description: User wants every casual/side request tracked as a to-do and written to memory
metadata: 
  node_type: memory
  type: feedback
---

The user said: "Alles, was ich dir so nebenbei schreibe bitte als To-Do tracken und in Memory schreiben."

**Why:** They drip-feed requirements across many short messages and don't want anything lost between turns.

**How to apply:** When the user mentions any new requirement in passing — even mid-task — immediately add it as a task (TaskCreate) and, if it's a durable requirement/preference, capture it in a memory file. Don't rely on it staying in conversation context. See [[antragsplattform-backlog]].
