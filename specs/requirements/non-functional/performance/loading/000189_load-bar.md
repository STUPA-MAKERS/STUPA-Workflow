---
id: "000189"
title: The load bar shows only for slow foreground reads
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit
scope:
  - frontend/vendor/ui-kit
---

# The load bar shows only for slow foreground reads

The load bar counts only a foreground GET. It shows after 300 ms and stays at least 400 ms. A
mutation, a background read, a read-ahead and a read with its own spinner must not count. They
opt out with `skipLoading()` or `quietly()`.
