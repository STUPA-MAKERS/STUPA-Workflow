---
id: "000323"
title: The done column sets the completion time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# The done column sets the completion time

A card that enters the done column must get `completed_at` and must write `todo_done` into
every linked ticket. A card that leaves it must lose `completed_at`. A cron must archive done
cards after `archive_after_days`.
