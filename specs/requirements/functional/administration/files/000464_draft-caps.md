---
id: "000464"
title: Wizard drafts are capped and expire
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/files/drafts.py
  - backend/worker/files_drafts.py
  - backend/app/settings.py
scope:
  - backend/app/settings.py
  - backend/app/modules/files
  - backend/worker/main.py
---

# Wizard drafts are capped and expire

A draft token must hold at most 20 files (`attachment_draft_max_files`) and 50 MiB
(`attachment_draft_max_bytes`). The hourly cron must delete drafts older than 7 days
(`attachment_draft_ttl_days`) with their objects.
