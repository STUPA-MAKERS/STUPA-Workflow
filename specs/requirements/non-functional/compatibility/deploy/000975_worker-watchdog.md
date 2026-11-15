---
id: "000975"
title: A worker that hangs ends its process
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/worker/main.py
  - deploy/docker-compose.yml
scope:
  - backend/worker
  - deploy/
---

# A worker that hangs ends its process

The worker must end its process when its event loop does not run for 120 seconds. The compose
file must start the worker again after each exit.

Reason: A health check only marks a container as unhealthy, and compose does not restart an
unhealthy container. A worker that hangs sends no mail, scans no file and makes no backup until
a person restarts it.

Test: A backend unit test blocks the event loop of the watchdog for longer than its limit and
finds the exit call.
