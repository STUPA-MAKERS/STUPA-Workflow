---
id: "000312"
title: Task reminders follow the admin setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/worker/task_reminders.py
  - backend/app/modules/notifications/service.py
scope:
  - backend/app/modules/notifications
  - backend/worker/mail.py
  - backend/worker
---

# Task reminders follow the admin setting

A task reminder must go out after `task_reminder_after_days` in one state and must repeat every
`task_reminder_repeat_days`. 0 means once per stay in the state. A state change must restart
the count.
