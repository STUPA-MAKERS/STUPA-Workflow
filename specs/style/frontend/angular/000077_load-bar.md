---
id: "000077"
title: Only foreground reads show the load bar
kind: style
status: replaced
owner: frederikbeimgraben
updated: 2026-11-05
replaced_by: NF/performance/loading/000189
scope:
  - frontend/
---

# Only foreground reads show the load bar

The load bar counts only GET requests in the foreground. A mutation never counts. A poll, a
refresh after a mutation, a typeahead and a load with its own spinner use `skipLoading()` or
`quietly()`.
