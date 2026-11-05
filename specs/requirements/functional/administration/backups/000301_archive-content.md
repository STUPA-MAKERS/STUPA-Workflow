---
id: "000301"
title: A backup holds the database and the attachments, encrypted
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/backup
  - backend/worker/backup.py
---

# A backup holds the database and the attachments, encrypted

A backup is an age-encrypted tar with a `pg_dump` of the database and a copy of the attachment
bucket. Without `backup_age_recipient`, every backup route answers 503.
