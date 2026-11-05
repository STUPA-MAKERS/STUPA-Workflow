---
id: "000157"
title: An admin merges two accounts
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# An admin merges two accounts

A holder of `admin.users.merge` merges an old principal into a new one in Verwaltung →
Benutzer. A preview shows what changes. Duplicates combine. A real conflict blocks the merge.
The old principal stays as a locked row "merged into". The display resolves old ids. The
audit log is not rewritten.
