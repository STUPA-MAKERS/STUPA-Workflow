---
id: "000312"
title: Task reminders follow the admin setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
  - backend/worker
---

# Task reminders follow the admin setting

A task reminder goes out after `task_reminder_after_days` in one state and repeats every
`task_reminder_repeat_days`. 0 means once per stay in the state. A state change restarts the
count.
