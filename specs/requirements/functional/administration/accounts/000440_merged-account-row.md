---
id: "000440"
title: A merged account stays as a locked row
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/admin/principal_merge.py
  - backend/app/modules/auth/identity.py
scope:
  - backend/app/modules/auth
  - backend/app/modules/admin
---

# A merged account stays as a locked row

After a merge, the old principal must stay as a locked row "merged into". The display must
resolve old IDs to the new principal. The merge must not rewrite the audit log.
