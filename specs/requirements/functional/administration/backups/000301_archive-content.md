---
id: "000301"
title: A backup holds the database and the attachments, encrypted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# A backup holds the database and the attachments, encrypted

A backup must be an age-encrypted tar with a `pg_dump` of the database and a copy of the
attachment bucket. Without `backup_age_recipient`, every backup route must answer 503.
