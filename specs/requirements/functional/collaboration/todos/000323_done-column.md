---
id: "000323"
title: The done column sets the completion time
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# The done column sets the completion time

A card that enters the done column gets `completed_at` and writes `todo_done` into every
linked ticket. A card that leaves it loses `completed_at`. A cron archives done cards after
`archive_after_days`.
